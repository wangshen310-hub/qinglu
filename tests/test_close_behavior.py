import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from recorder_ui import RecorderApp, load_settings, save_settings


class CloseBehaviorTests(unittest.TestCase):
    def app(self, action='隐藏到托盘', phase='idle'):
        app=object.__new__(RecorderApp)
        app.settings={'close_action':action}
        app.phase=phase;app.busy=False;app.animating=False;app.screenshot_busy=False
        app.root=Mock();app.tray=SimpleNamespace(ok=True)
        app.destroy=Mock();app.stop=Mock();app.cancel_countdown=Mock()
        app.close_after_save=False
        return app

    def test_hide_preserves_active_recording(self):
        app=self.app(phase='recording');app.close()
        app.root.withdraw.assert_called_once()
        app.stop.assert_not_called();app.destroy.assert_not_called()
        self.assertEqual(app.phase,'recording')

    def test_tray_unavailable_keeps_reachable_window(self):
        app=self.app();app.tray.ok=False
        with patch('recorder_ui.messagebox.showerror') as error:app.close()
        error.assert_called_once();app.root.withdraw.assert_not_called()
        app.destroy.assert_not_called()

    def test_busy_transition_does_not_hide(self):
        app=self.app();app.animating=True;app.close()
        app.root.withdraw.assert_not_called()

    def test_exit_setting_exits_idle(self):
        app=self.app('退出应用');app.close();app.destroy.assert_called_once()

    def test_explicit_tray_exit_ignores_hide_preference(self):
        app=self.app();app.exit_app();app.destroy.assert_called_once()

    def test_exit_recording_requires_save_confirmation(self):
        app=self.app(phase='recording')
        with patch('recorder_ui.messagebox.askyesno',return_value=True):app.exit_app()
        self.assertTrue(app.close_after_save);app.stop.assert_called_once()
        app.destroy.assert_not_called()

    def test_declining_exit_preserves_recording(self):
        app=self.app(phase='recording')
        with patch('recorder_ui.messagebox.askyesno',return_value=False):app.exit_app()
        app.destroy.assert_not_called();app.stop.assert_not_called()

    def test_settings_migrate_validate_and_persist(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            path.write_text(json.dumps({'fps':60}),encoding='utf-8')
            settings=load_settings(path)
            self.assertEqual(settings['close_action'],'退出应用')
            self.assertEqual(settings['fps'],60)
            settings['close_action']='隐藏到托盘';save_settings(settings,path)
            self.assertEqual(load_settings(path)['close_action'],'隐藏到托盘')
            settings['close_action']='invalid';save_settings(settings,path)
            self.assertEqual(load_settings(path)['close_action'],'退出应用')


if __name__=='__main__':unittest.main()
