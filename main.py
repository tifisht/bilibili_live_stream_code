import os
import sys

# [修复] 强制 Linux 下使用 x11 后端以支持 window.move (解决 Wayland 下无法拖拽的问题)
if sys.platform != 'win32':
    os.environ["GDK_BACKEND"] = "x11"

import webview
import logging
from logging.handlers import RotatingFileHandler
from backend.api_service import ApiService

# 获取日志目录
def get_log_path():
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    log_dir = os.path.join(base_path, 'logs')
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    return os.path.join(log_dir, 'app.log')

# 配置日志
log_file = get_log_path()
file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
stream_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)-15s - %(levelname)-8s - %(message)s',
    handlers=[file_handler, stream_handler]
)
# 屏蔽 urllib3 的 DEBUG 日志
logging.getLogger("urllib3").setLevel(logging.INFO)

logger = logging.getLogger("Main")
logger.info(f"Log file path: {log_file}")

def get_html_path():
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, 'frontend', 'dist', 'index.html')
    return os.path.join(os.getcwd(), 'frontend', 'dist', 'index.html')

if __name__ == '__main__':
    api = ApiService()
    window_width = 1000
    window_height = 720
    window = webview.create_window(
        'B站直播工具',
        url=get_html_path(),
        js_api=api,
        width=window_width,
        height=window_height,
        frameless=True,
        easy_drag=False, # [修复] 禁用 easy_drag，在 Linux (GDK_BACKEND=x11) 下依靠前端自定义拖拽
        # hidden=True
    )
    def center_and_show_window(window):
        primary_screen = webview.screens[0]
        x = (primary_screen.width - window.width) // 2
        y = (primary_screen.height - window.height) // 2
        window.move(x, y)
        
        # [修复] Windows 下无边框窗口无法通过任务栏图标最小化的问题
        if sys.platform == 'win32':
            try:
                import ctypes
                hwnd = None
                
                # 辅助函数：尝试将 Handle 转换为 int
                def get_hwnd(handle):
                    # 如果是 C# IntPtr 对象 (pythonnet)，通常有 ToInt64 方法
                    if hasattr(handle, 'ToInt64'):
                        return handle.ToInt64()
                    # 或者是 ToInt32
                    elif hasattr(handle, 'ToInt32'):
                        return handle.ToInt32()
                    else:
                        return int(handle)

                # 尝试获取窗口句柄 (兼容不同 pywebview 版本)
                if hasattr(window, 'gui') and hasattr(window.gui, 'Handle'):
                    hwnd = get_hwnd(window.gui.Handle)
                elif hasattr(window, 'native') and hasattr(window.native, 'Handle'):
                    hwnd = get_hwnd(window.native.Handle)
                
                if hwnd:
                    # GWL_STYLE = -16
                    user32 = ctypes.windll.user32
                    style = user32.GetWindowLongW(hwnd, -16)
                    
                    # 1. 去除 WS_THICKFRAME (0x00040000) 以消除顶部白条
                    #    之前的尝试中添加了这个样式导致了白条
                    style &= ~0x00040000
                    
                    # 2. 添加 WS_MINIMIZEBOX (0x00020000) 以支持任务栏点击最小化
                    style |= 0x00020000 
                    
                    user32.SetWindowLongW(hwnd, -16, style)
                    
                    # 刷新窗口状态
                    # SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED
                    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0002 | 0x0001 | 0x0004 | 0x0020)
            except Exception as e:
                logger.error(f"Failed to set window style: {e}")

        window.show()

    # --- 全局清理逻辑 ---
    def cleanup_services(api_service):
        """执行清理工作：停止直播、停止弹幕、保存配置"""
        try:
            # 1. 停止直播
            if api_service.session_state.is_live:
                api_service.live_service.stop_live()
            
            # 2. 停止弹幕
            import asyncio
            if api_service.loop:
                 asyncio.run_coroutine_threadsafe(api_service.danmu_service.stop(), api_service.loop)

            # 3. 保存配置
            api_service.config_manager.save()
            print("Services cleaned up.")
        except Exception as e:
            print(f"Cleanup failed: {e}")

    # --- 全局标志 ---
    import threading
    tray_state = {'is_exiting': False}
    tray_icon = None  # Windows pystray icon 引用

    # --- 通用托盘回调（跨平台共享） ---
    def tray_show_window():
        window.restore()
        window.show()

    def tray_start_live():
        user_config = api.user_service.load_saved_config()
        if user_config and 'last_area_name' in user_config:
            area = user_config['last_area_name']
            if isinstance(area, list) and len(area) >= 2:
                res = api.start_live(area[0], area[1])
            else:
                res = api.start_live()
        else:
            res = api.start_live()

        # 恢复并显示窗口
        window.restore()
        window.show()

        # 根据返回结果推送事件到前端
        if res and res.get('code') == 0:
            api.window_service.send_to_frontend("onTrayLiveStarted", res.get('data'))
        elif res and res.get('code') == 60024:
            api.window_service.send_to_frontend("onTrayNeedFaceVerify", res.get('qr', ''))
        else:
            msg = res.get('msg', '开播失败') if res else '开播失败'
            api.window_service.send_to_frontend("onTrayLiveError", msg)

    def tray_stop_live():
        res = api.stop_live()
        if res and res.get('code') == 0:
            api.window_service.send_to_frontend("onTrayLiveStopped", None)

    def tray_exit():
        global tray_icon
        tray_state['is_exiting'] = True

        # 停止托盘图标
        if sys.platform == 'win32':
            if tray_icon:
                tray_icon.stop()
        else:
            # Linux: 通过 Gtk.main_quit 停止 GTK 主循环
            try:
                import gi
                gi.require_version('Gtk', '3.0')
                from gi.repository import Gtk
                Gtk.main_quit()
            except Exception:
                pass

        print("Tray exit clicked. Cleaning up...")
        cleanup_services(api)

        print("Exiting application via Tray...")
        os._exit(0)

    # --- 通用 on_closing（跨平台共享） ---
    def on_closing():
        try:
            if tray_state['is_exiting']:
                return True  # 正在退出，允许关闭

            # 检查配置
            min_to_tray = True
            try:
                min_to_tray = api.config_manager.data.get("min_to_tray", True)
            except Exception as e:
                print(f"Error reading config: {e}")

            if min_to_tray:
                # 最小化到托盘
                window.hide()
                return False  # 阻止窗口关闭
            else:
                # 直接退出模式
                tray_state['is_exiting'] = True
                if sys.platform == 'win32' and tray_icon:
                    tray_icon.stop()

                cleanup_services(api)
                return True  # 允许窗口关闭 (pywebview 会退出)
        except Exception as e:
            print(f"Error in on_closing: {e}")
            return True

    window.events.closing += on_closing

    # --- 托盘图标逻辑 (平台分支) ---
    if sys.platform == 'win32':
        def create_tray_icon_win(window_obj):
            try:
                from PIL import Image
                import pystray
                from pystray import MenuItem as item
            except ImportError as e:
                print(f"Failed to import tray dependencies: {e}")
                return None

            def on_show(icon, item): tray_show_window()
            def on_start(icon, item): tray_start_live()
            def on_stop(icon, item): tray_stop_live()
            def on_quit(icon, item): tray_exit()

            # 加载图标
            icon_image = None
            try:
                if getattr(sys, 'frozen', False):
                    icon_path = os.path.join(sys._MEIPASS, 'bilibili.ico')
                else:
                    icon_path = os.path.join(os.getcwd(), 'bilibili.ico')
                icon_image = Image.open(icon_path)
            except Exception as e:
                logger.error(f"Failed to load tray icon: {e}")
                icon_image = Image.new('RGB', (64, 64), color='red')

            menu = pystray.Menu(
                item('显示主界面', on_show, default=True),
                item('开始直播', on_start),
                item('停止直播', on_stop),
                item('退出程序', on_quit)
            )

            icon = pystray.Icon("BiliLiveTool", icon_image, "B站直播工具", menu)
            return icon

        def run_tray_win():
            global tray_icon
            icon = create_tray_icon_win(window)
            if icon:
                tray_icon = icon
                tray_icon.run()

        threading.Thread(target=run_tray_win, daemon=True).start()

    else:
        # --- Linux 托盘 (AppIndicator3) ---
        def create_tray_icon_linux():
            try:
                import gi
                gi.require_version('Gtk', '3.0')
                gi.require_version('AyatanaAppIndicator3', '0.1')
                from gi.repository import Gtk, AyatanaAppIndicator3, GLib
            except (ImportError, ValueError) as e:
                print(f"Linux tray dependencies not found ({e}). Running without tray.")
                print("Install with: sudo apt install gir1.2-ayatanaappindicator3-0.1 gir1.2-gtk-3.0")
                return

            # 图标路径
            if getattr(sys, 'frozen', False):
                icon_path = os.path.join(sys._MEIPASS, 'bilibili.ico')
            else:
                icon_path = os.path.join(os.getcwd(), 'bilibili.ico')

            # 如果 .ico 存在但 AppIndicator 不支持，尝试 .png
            if not os.path.exists(icon_path):
                icon_path = icon_path.replace('.ico', '.png')

            indicator = AyatanaAppIndicator3.Indicator.new(
                "bili-live-tool",
                os.path.abspath(icon_path),
                AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS
            )
            indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)

            menu = Gtk.Menu()

            # 显示主界面
            item_show = Gtk.MenuItem(label='显示主界面')
            item_show.connect('activate', lambda _: GLib.idle_add(tray_show_window))
            menu.append(item_show)

            # 分隔线
            menu.append(Gtk.SeparatorMenuItem())

            # 开始直播
            item_start = Gtk.MenuItem(label='开始直播')
            item_start.connect('activate', lambda _: threading.Thread(target=tray_start_live, daemon=True).start())
            menu.append(item_start)

            # 停止直播
            item_stop = Gtk.MenuItem(label='停止直播')
            item_stop.connect('activate', lambda _: threading.Thread(target=tray_stop_live, daemon=True).start())
            menu.append(item_stop)

            # 分隔线
            menu.append(Gtk.SeparatorMenuItem())

            # 退出程序
            item_exit = Gtk.MenuItem(label='退出程序')
            item_exit.connect('activate', lambda _: tray_exit())
            menu.append(item_exit)

            menu.show_all()
            indicator.set_menu(menu)

            logger.info("Linux AppIndicator tray started.")
            Gtk.main()

        threading.Thread(target=create_tray_icon_linux, daemon=True).start()

    webview.start(center_and_show_window, window)

