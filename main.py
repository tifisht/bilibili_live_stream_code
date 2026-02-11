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

    # --- 托盘图标逻辑 (Windows Only) ---
    if sys.platform == 'win32':
        import threading
        from PIL import Image
        import pystray
        from pystray import MenuItem as item

        # 全局标志
        tray_state = {'is_exiting': False}
        tray_icon = None

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
            except Exception as e:
                logger.error(f"Cleanup failed: {e}")

        def create_tray_icon(api_service, window_obj):
            def on_show_window(icon, item):
                window_obj.restore()
                window_obj.show()

            def on_start_live(icon, item):
                user_config = api_service.user_service.load_saved_config()
                if user_config and 'last_area_name' in user_config:
                    area = user_config['last_area_name']
                    if isinstance(area, list) and len(area) >= 2:
                        api_service.start_live(area[0], area[1])
                    else:
                        api_service.start_live()
                else:
                    api_service.start_live()
                window_obj.show()

            def on_stop_live(icon, item):
                api_service.stop_live()

            def on_exit(icon, item):
                tray_state['is_exiting'] = True
                icon.stop()
                
                cleanup_services(api_service)

                # 销毁窗口，这会触发 closing 事件，但 is_exiting=True 会让它直接通过
                window_obj.destroy()
                os._exit(0)

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
                item('显示主界面', on_show_window, default=True),
                item('开始直播', on_start_live),
                item('停止直播', on_stop_live),
                item('退出程序', on_exit)
            )

            icon = pystray.Icon("BiliLiveTool", icon_image, "B站直播工具", menu)
            return icon

        def on_closing():
            if tray_state['is_exiting']:
                return True # 正在退出，允许关闭
            
            # 检查配置
            min_to_tray = api.config_manager.data.get("min_to_tray", True)
            
            if min_to_tray:
                # 最小化到托盘
                window.hide()
                return False # 阻止窗口关闭
            else:
                # 直接退出模式
                tray_state['is_exiting'] = True
                if tray_icon:
                    tray_icon.stop()
                
                cleanup_services(api)
                return True # 允许窗口关闭 (pywebview 会退出)

        # 启动托盘图标线程
        tray_icon = create_tray_icon(api, window)
        threading.Thread(target=tray_icon.run, daemon=True).start()


        # 绑定关闭事件
        window.events.closing += on_closing

    webview.start(center_and_show_window, window)
