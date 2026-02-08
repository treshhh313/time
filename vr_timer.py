import customtkinter as ctk
import pygame
import psutil
import threading
import time
import os
import sys
import json
from typing import Optional

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# --- Configuration & Constants ---
THEME_COLOR = "#8A2BE2"  # BlueViolet
HOVER_COLOR = "#9400D3"  # DarkViolet
FONT_MAIN = "Roboto"
WINDOW_SIZE = "300x520" # Narrow vertical layout
APP_TITLE = "VR Timer"

# Audio Config
AUDIO_FILES = {
    "15m": "warning_15m.mp3",
    "5m": "warning_5m.mp3",
    "finish": "finish.mp3"
}

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# --- Managers ---

class ConfigManager:
    """Handles loading and saving configuration."""
    def __init__(self, filename="config.json"):
        # Determine persistent path (next to exe or script)
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
            
        self.filename = os.path.join(base_path, filename)
        
        self.defaults = {
            "buffer_seconds": 20,
            "kill_delay_seconds": 30,
            "process_name": "vrmonitor.exe"
        }
        self.config = self.load_config()

    def load_config(self):
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r') as f:
                    return json.load(f)
            return self.defaults.copy()
        except Exception as e:
            print(f"Config Load Error: {e}")
            return self.defaults.copy()

    def save_config(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Config Save Error: {e}")

    def get(self, key):
        return self.config.get(key, self.defaults.get(key))

    def set(self, key, value):
        self.config[key] = value

class SoundManager:
    """Handles MP3 playback using Pygame with Voice Packs."""
    def __init__(self):
        try:
            pygame.mixer.init()
            self.volume = 1.0
            self.current_pack = "v1" # v1 or v2
        except Exception as e:
            print(f"Audio Init Error: {e}")

    def toggle_pack(self) -> str:
        self.current_pack = "v2" if self.current_pack == "v1" else "v1"
        return self.current_pack

    def set_volume(self, value: float):
        """Set volume (0.0 to 1.0)"""
        self.volume = max(0.0, min(1.0, value))
        # Logic to update running sounds if needed, but for notifications 
        # usually setting mixer volume affects future plays or we set channel volume.
        # pygame.mixer.Sound.set_volume works per sound.
        # We'll set it when playing or use a global channel approach if needed.
        # Simple approach: Store volume and apply on play.

    def play(self, key: str):
        # Construct filename: e.g. "v1_warning_15m.mp3"
        base_name = AUDIO_FILES.get(key)
        if not base_name:
            return
            
        filename = f"{self.current_pack}_{base_name}"
        
        # Try local first, then bundled
        local_path = os.path.abspath(filename)
        if not os.path.exists(local_path):
            filename = resource_path(filename)
        else:
            filename = local_path
        
        if not os.path.exists(filename):
            print(f"[AUDIO MISSING] File not found: {filename}")
            return

        def _play():
            try:
                sound = pygame.mixer.Sound(filename)
                sound.set_volume(self.volume)
                sound.play()
            except Exception as e:
                print(f"Audio Play Error ({filename}): {e}")
        
        # Run in thread to not block UI (though pygame mixer is async usually, loading might block)
        threading.Thread(target=_play, daemon=True).start()


class TimerThread(threading.Thread):
    """Timer Logic running in a separate thread."""
    def __init__(self, duration_minutes: int, on_tick, on_finish, on_warning):
        super().__init__(daemon=True)
        self.total_seconds = int(duration_minutes * 60)
        self.remaining_seconds = self.total_seconds
        self.on_tick = on_tick
        self.on_finish = on_finish
        self.on_warning = on_warning
        
        self.running = False
        self.paused = False
        self._stop_event = threading.Event()

    def run(self):
        self.running = True
        while self.remaining_seconds > 0 and not self._stop_event.is_set():
            if self.paused:
                time.sleep(0.1)
                continue
            
            # Logic Check: 15 minute warning
            if self.remaining_seconds == 15 * 60:
                 self.on_warning(15)

            # Logic Check: 5 minute warning
            if self.remaining_seconds == 5 * 60:
                self.on_warning(5)

            # Update UI
            self.on_tick(self.remaining_seconds, self.total_seconds)
            
            time.sleep(1)
            self.remaining_seconds -= 1

        if not self._stop_event.is_set():
            # Timer finished naturally
            self.on_tick(0, self.total_seconds)
            self.on_finish()
        
        self.running = False

    def pause(self):
        self.paused = not self.paused

    def add_time(self, minutes: int):
        self.remaining_seconds += minutes * 60
        self.total_seconds = max(self.total_seconds, self.remaining_seconds)

    def stop(self):
        self._stop_event.set()


# --- UI ---

class VRTimerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title(APP_TITLE)
        self.geometry(WINDOW_SIZE)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        
        # Managers
        self.config_manager = ConfigManager()
        self.sound_manager = SoundManager()
        self.timer_thread: Optional[TimerThread] = None

        # Variables
        self.custom_time_var = ctk.StringVar(value="60")
        
        # Settings Vars
        self.var_buffer = ctk.StringVar(value=str(self.config_manager.get("buffer_seconds")))
        self.var_kill_delay = ctk.StringVar(value=str(self.config_manager.get("kill_delay_seconds")))
        self.var_process_name = ctk.StringVar(value=self.config_manager.get("process_name"))
        
        # Hidden Trigger vars
        self.click_count = 0
        self.last_click_time = 0
        
        self.is_mini_mode = False
        
        self._init_ui()

    def _init_ui(self):
        # Configure grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Tab View
        self.tab_view = ctk.CTkTabview(self)
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.tab_view.add("Таймер")
        self.tab_view.add("Настройки")

        # --- TAB: TIMER ---
        self.timer_frame = self.tab_view.tab("Таймер")
        self.timer_frame.grid_columnconfigure(0, weight=1)

        # --- HIDDEN TRIGGER (Moved to Tab Timer logic effectively, or kept global but placed in tab) ---
        # Actually better to place it on the main window or the tab frame. 
        # Let's place it on the timer frame to avoid overlay issues with tabs.
        self.btn_hidden = ctk.CTkButton(self.timer_frame, text="", fg_color="transparent", hover_color=THEME_COLOR, width=50, height=50, command=self.on_hidden_click)
        self.btn_hidden.place(x=0, y=0) 
        self.btn_hidden.configure(hover_color=THEME_COLOR)

        # 1. Header/Status
        self.lbl_status = ctk.CTkLabel(self.timer_frame, text="Ожидание", text_color="gray", font=(FONT_MAIN, 16, "italic"))
        self.lbl_status.grid(row=0, column=0, pady=(10, 5))

        # 2. Timer Display (Big)
        self.lbl_time = ctk.CTkLabel(self.timer_frame, text="00:00:00", font=(FONT_MAIN, 58, "bold")) # Reduced font size
        self.lbl_time.grid(row=1, column=0, pady=10)
        
        self.progress_bar = ctk.CTkProgressBar(self.timer_frame, orientation="horizontal", mode="determinate", width=250)
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=10)
        self.progress_bar.set(0)
        self.progress_bar.configure(progress_color=THEME_COLOR)

        # 3. Quick Time Buttons (Grid Layout)
        self.frm_quick_buttons = ctk.CTkFrame(self.timer_frame, fg_color="transparent")
        self.frm_quick_buttons.grid(row=3, column=0, pady=5)
        
        btn_params = {
            "fg_color": "transparent", 
            "border_width": 2, 
            "border_color": THEME_COLOR, 
            "text_color": "white", 
            "hover_color": THEME_COLOR,
            "width": 80,
            "height": 35,
            "font": (FONT_MAIN, 12, "bold")
        }
        
        def create_btn(txt, mins, col):
            cmd = lambda: self.start_timer(mins)
            ctk.CTkButton(self.frm_quick_buttons, text=txt, command=cmd, **btn_params).grid(row=0, column=col, padx=5)

        create_btn("15m", 15, 0)
        create_btn("30m", 30, 1)
        create_btn("60m", 60, 2)

        # 4. Custom Time Input
        self.frm_custom_time = ctk.CTkFrame(self.timer_frame, fg_color="transparent")
        self.frm_custom_time.grid(row=4, column=0, pady=10)
        
        ctk.CTkEntry(self.frm_custom_time, textvariable=self.custom_time_var, width=60, justify="center", font=(FONT_MAIN, 14)).pack(side="left", padx=5)
        ctk.CTkButton(self.frm_custom_time, text="Старт", command=lambda: self.start_custom_timer(), fg_color=THEME_COLOR, hover_color=HOVER_COLOR, width=80).pack(side="left", padx=5)

        # 5. Controls (2x2 Grid)
        self.frm_controls = ctk.CTkFrame(self.timer_frame, fg_color="transparent")
        self.frm_controls.grid(row=5, column=0, pady=10)
        
        control_params = {"width": 110, "height": 35}
        
        self.btn_pause = ctk.CTkButton(self.frm_controls, text="Пауза", command=self.pause_timer, state="disabled", fg_color="#FFA500", hover_color="#CD8500", **control_params)
        self.btn_pause.grid(row=0, column=0, padx=5, pady=5)
        
        self.btn_stop = ctk.CTkButton(self.frm_controls, text="Сброс", command=self.stop_timer, state="disabled", fg_color="#DC143C", hover_color="#8B0000", **control_params)
        self.btn_stop.grid(row=0, column=1, padx=5, pady=5)
        
        self.btn_add = ctk.CTkButton(self.frm_controls, text="+5 мин", command=self.add_time, state="disabled", fg_color=THEME_COLOR, hover_color=HOVER_COLOR, **control_params)
        self.btn_add.grid(row=1, column=0, columnspan=2, pady=5, sticky="ew")

        # 6. Volume Control
        self.frm_volume = ctk.CTkFrame(self.timer_frame, fg_color="transparent")
        self.frm_volume.grid(row=6, column=0, pady=(5, 10))

        # Compact Volume
        ctk.CTkLabel(self.frm_volume, text="🔊", font=(FONT_MAIN, 16)).pack(side="left", padx=5)
        self.slider_volume = ctk.CTkSlider(self.frm_volume, from_=0, to=1, command=self.on_volume_change, width=180, progress_color=THEME_COLOR)
        self.slider_volume.pack(side="left", padx=5)
        self.slider_volume.set(1.0) 

        # 7. Auto-Hover Logic (Starts automatically)
        self.hover_check_job = None
        self.start_hover_check()

        # --- MINI MODE UI (Hidden by default) ---
        self.mini_frame = ctk.CTkFrame(self, fg_color="transparent")
        
        # Simple mini layout: Just time
        self.lbl_mini_time = ctk.CTkLabel(self.mini_frame, text="00:00:00", font=(FONT_MAIN, 40, "bold"))
        self.lbl_mini_time.pack(expand=True)
        
        # --- TAB: SETTINGS ---
        self.settings_frame = self.tab_view.tab("Настройки")
        self.settings_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.settings_frame, text="Настройки времени", font=(FONT_MAIN, 20, "bold")).pack(pady=20)

        # Buffer
        ctk.CTkLabel(self.settings_frame, text="Буфер при старте (сек):").pack(pady=5)
        ctk.CTkEntry(self.settings_frame, textvariable=self.var_buffer).pack(pady=5)

        # Kill Delay
        ctk.CTkLabel(self.settings_frame, text="Задержка закрытия SteamVR (сек):").pack(pady=5)
        ctk.CTkEntry(self.settings_frame, textvariable=self.var_kill_delay).pack(pady=5)

        # Process Name
        ctk.CTkLabel(self.settings_frame, text="Имя процесса VR:").pack(pady=5)
        ctk.CTkEntry(self.settings_frame, textvariable=self.var_process_name).pack(pady=5)

        # Save Button
        ctk.CTkButton(self.settings_frame, text="Сохранить настройки", command=self.save_settings, fg_color=THEME_COLOR, hover_color=HOVER_COLOR).pack(pady=20)

    def save_settings(self):
        try:
            buffer = int(self.var_buffer.get())
            kill = int(self.var_kill_delay.get())
            proc = self.var_process_name.get()
            
            self.config_manager.set("buffer_seconds", buffer)
            self.config_manager.set("kill_delay_seconds", kill)
            self.config_manager.set("process_name", proc)
            self.config_manager.save_config()
            
            self.show_toast("Настройки сохранены!")
        except ValueError:
            self.show_toast("Ошибка: введите числа!")

    def start_hover_check(self):
        self.check_hover()
    
    def check_hover(self):
        try:
            # Get mouse position
            x, y = self.winfo_pointerxy()
            
            # Get window position and size
            win_x = self.winfo_rootx()
            win_y = self.winfo_rooty()
            win_w = self.winfo_width()
            win_h = self.winfo_height()
            
            # Check if mouse is inside window
            is_inside = (win_x <= x <= win_x + win_w) and (win_y <= y <= win_y + win_h)
            
            if is_inside:
                if self.is_mini_mode:
                    self.expand_ui()
            else:
                if not self.is_mini_mode:
                    self.minimize_ui()
                    
        except Exception:
            pass
            
        # Schedule next check
        self.hover_check_job = self.after(200, self.check_hover)

    def minimize_ui(self):
        if self.is_mini_mode: return
        self.is_mini_mode = True
        
        self.tab_view.grid_forget()
        self.mini_frame.place(relx=0.5, rely=0.5, anchor="center")
        self.geometry("250x60") # Slightly smaller height 

    def expand_ui(self):
        if not self.is_mini_mode: return
        self.is_mini_mode = False
        
        self.mini_frame.place_forget()
        self.tab_view.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.geometry(WINDOW_SIZE)

    # --- Timer Control Methods ---

    def start_custom_timer(self):
        try:
            mins = int(self.custom_time_var.get())
            if mins > 0:
                self.start_timer(mins, use_buffer=False) 
        except ValueError:
            pass

    def start_timer(self, minutes: float, use_buffer=True):
        if self.timer_thread and self.timer_thread.is_alive():
            self.stop_timer()

        duration = minutes
        buffer_sec = 0
        if use_buffer:
             buffer_sec = self.config_manager.get("buffer_seconds")
             duration += (buffer_sec / 60)

        display_min = int(minutes)
        status_txt = f"Сессия запущена ({display_min} мин)"
        if use_buffer:
            status_txt += f" + {buffer_sec} сек"
            
        self.lbl_status.configure(text=status_txt, text_color="#55FF55")
        self.set_controls_state("normal")
        
        self.timer_thread = TimerThread(
            duration_minutes=duration,
            on_tick=self.on_tick,
            on_finish=self.on_finish,
            on_warning=self.on_warning
        )
        self.timer_thread.start()

    def pause_timer(self):
        if self.timer_thread:
            self.timer_thread.pause()
            new_text = "Продолжить" if self.timer_thread.paused else "Пауза"
            self.btn_pause.configure(text=new_text)
            status_text = "Пауза" if self.timer_thread.paused else "Сессия запущена"
            self.lbl_status.configure(text=status_text, text_color="orange" if self.timer_thread.paused else "#55FF55")

    def stop_timer(self):
        if self.timer_thread:
            self.timer_thread.stop()
            self.timer_thread.join(timeout=0.5) 
            self.timer_thread = None
        
        self.lbl_status.configure(text="Сессия остановлена", text_color="white")
        self.lbl_time.configure(text="00:00:00")
        self.lbl_mini_time.configure(text="00:00:00")
        self.progress_bar.set(0)
        self.set_controls_state("disabled")
        self.btn_pause.configure(text="Пауза")

    def add_time(self):
        if self.timer_thread:
            self.timer_thread.add_time(5)

    def on_volume_change(self, value):
        self.sound_manager.set_volume(float(value))

    def set_controls_state(self, state):
        self.btn_pause.configure(state=state)
        self.btn_stop.configure(state=state)
        self.btn_add.configure(state=state)

    # --- Callbacks ---
    
    def on_tick(self, remaining: int, total: int):
        self.after(0, lambda: self._update_ui_tick(remaining, total))

    def _update_ui_tick(self, remaining: int, total: int):
        mins, secs = divmod(remaining, 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{hours:02}:{mins:02}:{secs:02}"
        
        self.lbl_time.configure(text=time_str)
        self.lbl_mini_time.configure(text=time_str)
        
        if total > 0:
            progress = remaining / total
            self.progress_bar.set(progress)

    def on_warning(self, minutes: int):
        key = "15m" if minutes == 15 else "5m"
        self.sound_manager.play(key)
        self.after(0, lambda: self.lbl_status.configure(text=f"ВНИМАНИЕ: {minutes} МИНУТ", text_color="yellow"))

    def on_finish(self):
        self.after(0, self._handle_finish)

    def _handle_finish(self):
        self.lbl_status.configure(text="Сеанс завершен", text_color="#FF5555")
        self.lbl_time.configure(text="00:00:00")
        self.lbl_mini_time.configure(text="00:00:00")
        self.progress_bar.set(0)
        self.set_controls_state("disabled")
        
        self.sound_manager.play("finish")
        
        # Schedule SteamVR kill 
        delay = self.config_manager.get("kill_delay_seconds")
        print(f"Scheduling SteamVR kill in {delay} seconds...")
        threading.Timer(float(delay), self._kill_steam_vr).start()

    def _kill_steam_vr(self):
        """Attempts to kill process (SteamVR) if running."""
        target_process = self.config_manager.get("process_name")
        killed = False
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                if proc.info['name'] and proc.info['name'].lower() == target_process.lower():
                    proc.kill()
                    killed = True
                    print(f"Killed {target_process} (PID: {proc.info['pid']})")
            
            if not killed:
                print(f"{target_process} not found.")
                
        except Exception as e:
            print(f"Error killing SteamVR: {e}")

    # --- Hidden Features ---

    def on_hidden_click(self):
        current_time = time.time()
        # Reset if too slow (more than 1 sec between clicks)
        if current_time - self.last_click_time > 1.0:
            self.click_count = 0
        
        self.click_count += 1
        self.last_click_time = current_time
        
        if self.click_count >= 3:
            self.click_count = 0
            new_pack = self.sound_manager.toggle_pack()
            self.show_toast(f"Озвучка изменена: {new_pack.upper()}")

    def show_toast(self, message):
        toast = ctk.CTkLabel(self, text=message, fg_color="#333333", text_color="white", corner_radius=10, padx=20, pady=10)
        toast.place(relx=0.5, rely=0.1, anchor="center")
        # Auto hide after 2 seconds
        self.after(2000, toast.destroy)


if __name__ == "__main__":
    app = VRTimerApp()
    app.mainloop()
