import customtkinter as ctk
import pyttsx3
import threading
import time
from typing import Optional

# --- Configuration & Constants ---
THEME_COLOR = "#8A2BE2"  # BlueViolet
HOVER_COLOR = "#9400D3"  # DarkViolet
FONT_MAIN = "Roboto"
WINDOW_SIZE = "700x500"
APP_TITLE = "VR Club Timer"

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# --- Managers ---

class SoundManager:
    """Handles Text-to-Speech notifications."""
    def __init__(self):
        try:
            self.engine = pyttsx3.init()
            self.engine.setProperty('rate', 150)
        except Exception as e:
            print(f"TTS Init Error: {e}")
            self.engine = None

    def speak(self, text: str):
        if self.engine:
            def _speak():
                try:
                    self.engine.say(text)
                    self.engine.runAndWait()
                except Exception as e:
                    print(f"TTS Speak Error: {e}")
            
            threading.Thread(target=_speak, daemon=True).start()
        else:
            print(f"[TTS DISABLED] {text}")


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
        self.warning_triggered = False

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
        
        # Managers
        self.sound_manager = SoundManager()
        self.timer_thread: Optional[TimerThread] = None

        # Variables
        self.custom_time_var = ctk.StringVar(value="60")
        
        self._init_ui()

    def _init_ui(self):
        # Configure grid layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main container
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)

        # 1. Header/Status
        self.lbl_status = ctk.CTkLabel(self.main_frame, text="Ожидание", text_color="gray", font=(FONT_MAIN, 24, "italic"))
        self.lbl_status.grid(row=0, column=0, pady=(20, 10))

        # 2. Timer Display (Big)
        self.lbl_time = ctk.CTkLabel(self.main_frame, text="00:00:00", font=(FONT_MAIN, 80, "bold"))
        self.lbl_time.grid(row=1, column=0, pady=20)
        
        self.progress_bar = ctk.CTkProgressBar(self.main_frame, orientation="horizontal", mode="determinate")
        self.progress_bar.grid(row=2, column=0, sticky="ew", padx=40, pady=20)
        self.progress_bar.set(0)
        self.progress_bar.configure(progress_color=THEME_COLOR)

        # 3. Quick Time Buttons (With +2 min buffer)
        self.frm_quick_buttons = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.frm_quick_buttons.grid(row=3, column=0, pady=20)
        
        btn_params = {
            "fg_color": "transparent", 
            "border_width": 2, 
            "border_color": THEME_COLOR, 
            "text_color": "white", 
            "hover_color": THEME_COLOR,
            "width": 100,
            "height": 40,
            "font": (FONT_MAIN, 14, "bold")
        }
        
        # Helper to create styled buttons
        def create_btn(txt, mins):
            cmd = lambda: self.start_timer(mins + 2) # Adding 2 minute buffer
            ctk.CTkButton(self.frm_quick_buttons, text=txt, command=cmd, **btn_params).pack(side="left", padx=10)

        create_btn("15 мин", 15)
        create_btn("30 мин", 30)
        create_btn("60 мин", 60)

        # 4. Custom Time Input
        self.frm_custom_time = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.frm_custom_time.grid(row=4, column=0, pady=10)
        
        ctk.CTkEntry(self.frm_custom_time, textvariable=self.custom_time_var, width=80, justify="center", font=(FONT_MAIN, 14)).pack(side="left", padx=10)
        ctk.CTkButton(self.frm_custom_time, text="Старт (без буфера)", command=lambda: self.start_custom_timer(), fg_color=THEME_COLOR, hover_color=HOVER_COLOR).pack(side="left", padx=10)

        # 5. Controls (Pause/Stop/Add)
        self.frm_controls = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.frm_controls.grid(row=5, column=0, pady=30)
        
        control_params = {"width": 120, "height": 40}
        
        self.btn_pause = ctk.CTkButton(self.frm_controls, text="Пауза", command=self.pause_timer, state="disabled", fg_color="#FFA500", hover_color="#CD8500", **control_params)
        self.btn_pause.pack(side="left", padx=10)
        
        self.btn_stop = ctk.CTkButton(self.frm_controls, text="Стоп/Сброс", command=self.stop_timer, state="disabled", fg_color="#DC143C", hover_color="#8B0000", **control_params)
        self.btn_stop.pack(side="left", padx=10)
        
        self.btn_add = ctk.CTkButton(self.frm_controls, text="+5 мин", command=self.add_time, state="disabled", fg_color=THEME_COLOR, hover_color=HOVER_COLOR, **control_params)
        self.btn_add.pack(side="left", padx=10)

    # --- Timer Control Methods ---

    def start_custom_timer(self):
        try:
            mins = int(self.custom_time_var.get())
            if mins > 0:
                self.start_timer(mins) # No buffer for custom time unless requested? User said "presets", assuming custom is strict.
        except ValueError:
            pass

    def start_timer(self, minutes: int):
        # Prevent starting if already running
        if self.timer_thread and self.timer_thread.is_alive():
            self.stop_timer()

        self.lbl_status.configure(text=f"Сессия запущена ({minutes} мин)", text_color="#55FF55")
        self.set_controls_state("normal")
        
        # Start Thread
        self.timer_thread = TimerThread(
            duration_minutes=minutes,
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
        self.progress_bar.set(0)
        self.set_controls_state("disabled")
        self.btn_pause.configure(text="Пауза")

    def add_time(self):
        if self.timer_thread:
            self.timer_thread.add_time(5)

    def set_controls_state(self, state):
        self.btn_pause.configure(state=state)
        self.btn_stop.configure(state=state)
        self.btn_add.configure(state=state)

    # --- Callbacks (Thread-Safe UI Updates) ---
    
    def on_tick(self, remaining: int, total: int):
        self.after(0, lambda: self._update_ui_tick(remaining, total))

    def _update_ui_tick(self, remaining: int, total: int):
        mins, secs = divmod(remaining, 60)
        hours, mins = divmod(mins, 60)
        time_str = f"{hours:02}:{mins:02}:{secs:02}"
        
        self.lbl_time.configure(text=time_str)
        
        if total > 0:
            progress = remaining / total
            self.progress_bar.set(progress)

    def on_warning(self, minutes: int):
        self.sound_manager.speak(f"Уважаемый игрок, до конца сеанса осталось {minutes} минут")
        self.after(0, lambda: self.lbl_status.configure(text=f"ВНИМАНИЕ: {minutes} МИНУТ", text_color="yellow"))

    def on_finish(self):
        self.after(0, self._handle_finish)

    def _handle_finish(self):
        self.lbl_status.configure(text="Сеанс завершен", text_color="#FF5555")
        self.lbl_time.configure(text="00:00:00")
        self.progress_bar.set(0)
        self.set_controls_state("disabled")
        
        self.sound_manager.speak("Время сеанса вышло")


if __name__ == "__main__":
    app = VRTimerApp()
    app.mainloop()
