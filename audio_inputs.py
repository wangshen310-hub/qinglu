"""Independent, timestamped microphone and loopback inputs."""
import time
import wave
import numpy as np
import pyaudiowpatch as pa
from audio_timeline import AudioTimeline

def microphone_devices(audio):
    host=audio.get_host_api_info_by_type(pa.paWASAPI)['index']
    return [d for i in range(audio.get_device_count())
            if (d:=audio.get_device_info_by_index(i))['hostApi']==host
            and d['maxInputChannels']>0 and not d.get('isLoopbackDevice')]

def choose_microphone(audio,name):
    devices=microphone_devices(audio)
    if name!='自动选择麦克风':
        for d in devices:
            if d['name']==name:return d
        raise RuntimeError('所选麦克风已断开，请在设置中重新选择。')
    for d in devices:
        if any(word in d['name'].lower() for word in ('麦克风','microphone','mic ')):return d
    return audio.get_device_info_by_index(audio.get_host_api_info_by_type(pa.paWASAPI)['defaultInputDevice'])


class AudioInputs:
    def __init__(self, owner):
        self.owner=owner;self.audio=pa.PyAudio();self.tracks=[]
        try:
            for name,enabled,gain,mute in (
                ('computer',owner.sound,owner.system_volume,owner.muted),
                ('microphone',owner.microphone,owner.microphone_volume,owner.mic_muted)):
                if not enabled:continue
                try:
                    device=(self.audio.get_default_wasapi_loopback() if name=='computer'
                            else choose_microphone(self.audio,owner.microphone_device))
                    if name=='microphone' and device.get('isLoopbackDevice'):
                        raise RuntimeError('默认输入设备是回录设备，请在 Windows 设置中选择麦克风。')
                    rate=int(device['defaultSampleRate']);channels=min(2,int(device['maxInputChannels']))
                    if channels<1:raise RuntimeError('设备没有输入声道')
                    track=dict(name=name,path=owner.work/f'{name}{owner.index}.wav',rate=rate,
                               channels=channels,gain=gain/100,mute=mute,timeline=None,stream=None)
                    self.tracks.append(track)
                    def callback(data,frames,timing,status,t=track):
                        try:
                            adc=timing['input_buffer_adc_time']
                            if adc<=0:raise RuntimeError('音频设备未提供有效采集时间戳')
                            if t['mute'].is_set():data=bytes(len(data))
                            elif t['gain']!=1:
                                data=(np.frombuffer(data,dtype=np.int16).astype(np.float32)*t['gain']).astype(np.int16).tobytes()
                            t['timeline'].submit(data,adc+t['offset'])
                        except Exception as exc:
                            owner.audio_error=f"{t['name']}: {exc}";return None,pa.paAbort
                        return None,pa.paContinue
                    stream=self.audio.open(format=pa.paInt16,channels=channels,rate=rate,input=True,
                        input_device_index=device['index'],frames_per_buffer=1024,stream_callback=callback,start=False)
                    track['stream']=stream
                    before=time.time();clock=stream.get_time();after=time.time()
                    track['offset']=(before+after)/2-clock
                except Exception as exc:
                    label='麦克风' if name=='microphone' else '电脑声音'
                    hint='\n请检查 Windows 麦克风访问、桌面应用权限，以及所选设备是否已连接。' if name=='microphone' else ''
                    raise RuntimeError(f'{label}无法打开：{exc}{hint}') from exc
        except Exception:
            self.close();raise

    def start(self,origin):
        for t in self.tracks:
            t['timeline']=AudioTimeline(t['path'],t['rate'],t['channels'],origin)
            t['stream'].start_stream()

    def close(self):
        for t in self.tracks:
            stream=t['stream'];t['stream']=None
            if stream:
                try:stream.stop_stream()
                except Exception as exc:self.owner.audio_error=str(exc)
                finally:stream.close()
            if t['timeline']:
                timeline=t['timeline'];t['timeline']=None
                try:timeline.close()
                except Exception as exc:self.owner.audio_error=str(exc)
                t['gap']=timeline.inserted_silence/timeline.rate
        if self.audio:self.audio.terminate();self.audio=None

    def mix_args(self,offset):
        inputs=[];filters=[]
        for i,t in enumerate(self.tracks,1):
            with wave.open(str(t['path']),'rb') as f:empty=f.getnframes()==0;params=f.getparams()
            if empty:
                with wave.open(str(t['path']),'wb') as f:
                    f.setparams(params);f.writeframes(bytes(params.nchannels*2*max(1,round((.1+max(0,offset))*params.framerate))))
            inputs+=['-i',str(t['path'])]
            align=(f'atrim=start={offset:.9f},asetpts=PTS-STARTPTS' if offset>=0
                   else f'adelay={round(-offset*1000)}:all=1')
            filters.append(f'[{i}:a]{align},aresample=48000,aformat=channel_layouts=stereo,apad[a{i}]')
        if len(self.tracks)==2:
            filters.append('[a1][a2]amix=inputs=2:normalize=0,alimiter=limit=0.95:level=0:latency=1[mix]')
            output='[mix]'
        else:output='[a1]'
        return inputs+['-filter_complex',';'.join(filters),'-map','0:v:0','-map',output]
