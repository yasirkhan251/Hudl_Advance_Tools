from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

import keyboard
import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

BASE_DIR = Path(__file__).resolve().parent
COORDINATES_FILE = BASE_DIR / "coordinates.json"

DEFAULT_TARGET_COORD = (1698, 391)
DEFAULT_PLAYBACK_COORDS = {
    "menu": (1572, 899),
    "0.5x": (1486, 765),
    "1x": (1519, 764),
    "1.5x": (1549, 762),
    "2x": (1578, 761),
    "2.5x": (1606, 762),
    "exit_menu": (1417, 771),
}
PLAYBACK_SPEEDS = ("0.5x", "1x", "1.5x", "2x", "2.5x")
CALIBRATION_STEPS = (
    ("menu", "Playback speed menu"),
    ("0.5x", "0.5x speed option"),
    ("1x", "1x speed option"),
    ("1.5x", "1.5x speed option"),
    ("2x", "2x speed option"),
    ("2.5x", "2.5x speed option"),
    ("exit_menu", "Close-menu point"),
)


class InteractiveHudlTagger:
    """Hudl tagger with global shortcuts so Hudl can remain focused."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Hudl Auto-Tagger")
        self.root.geometry("560x420")
        self.root.minsize(520, 390)
        self.root.attributes("-topmost", False)

        self.coordinates = self._load_coordinates()
        self.target_coord = tuple(self.coordinates["target_coord"])
        self.playback_coords = {
            key: tuple(value)
            for key, value in self.coordinates["playback_coords"].items()
        }

        # Speed starts at 1x as requested. This is a local assumption, not
        # automatic detection of Hudl's currently selected playback speed.
        self.current_speed_index = PLAYBACK_SPEEDS.index("1x")
        self.pending_speed_index: int | None = None
        self._speed_select_after: str | None = None
        self._close_menu_after: str | None = None

        self.overlay: tk.Toplevel | None = None
        self.calibration_index = 0
        self._global_hotkey_ids = []
        self._global_action_running = False

        self._build_ui()
        self._bind_app_hotkeys()
        self._register_global_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Coordinates JSON
    # ------------------------------------------------------------------
    def _load_coordinates(self) -> dict:
        data = {
            "target_coord": list(DEFAULT_TARGET_COORD),
            "playback_coords": {
                key: list(value)
                for key, value in DEFAULT_PLAYBACK_COORDS.items()
            },
        }

        try:
            if COORDINATES_FILE.exists():
                with COORDINATES_FILE.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)

                target = loaded.get("target_coord")
                if self._is_coordinate(target):
                    data["target_coord"] = [int(target[0]), int(target[1])]

                loaded_playback = loaded.get("playback_coords", {})
                if isinstance(loaded_playback, dict):
                    for key in DEFAULT_PLAYBACK_COORDS:
                        coordinate = loaded_playback.get(key)
                        if self._is_coordinate(coordinate):
                            data["playback_coords"][key] = [
                                int(coordinate[0]),
                                int(coordinate[1]),
                            ]
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"Could not read {COORDINATES_FILE.name}: {error}")

        return data

    @staticmethod
    def _is_coordinate(value) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and all(isinstance(part, (int, float)) for part in value)
        )

    def _save_coordinates(self) -> None:
        data = {
            "target_coord": list(self.target_coord),
            "playback_coords": {
                key: list(self.playback_coords[key])
                for key in DEFAULT_PLAYBACK_COORDS
            },
        }
        temp_file = COORDINATES_FILE.with_suffix(".json.tmp")

        try:
            with temp_file.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=4)
                file.write("\n")
            os.replace(temp_file, COORDINATES_FILE)
            self.coordinates = data
        except OSError as error:
            messagebox.showerror(
                "Coordinate Save Failed",
                f"Could not save coordinates to:\n{COORDINATES_FILE}\n\n{error}",
                parent=self.root,
            )
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # UI and Tkinter-only hotkeys
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        tk.Label(
            self.root,
            text="Hudl Interactive Tagger",
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=(14, 5))

        tk.Label(
            self.root,
            text="O: slower   P: faster   N/T/W: quick commands   X: exit",
            fg="#1d4ed8",
            font=("Segoe UI", 9, "bold"),
        ).pack(pady=3)

        self.status = tk.Label(
            self.root,
            text="Ready — keep Hudl focused and use O/P/N/T/W.",
            fg="#334155",
            wraplength=510,
            justify="center",
        )
        self.status.pack(pady=7)

        self.entry = tk.Entry(
            self.root,
            font=("Consolas", 14),
            width=22,
            justify="center",
        )
        self.entry.pack(pady=7)
        self.entry.bind("<Return>", lambda event: self.run_complex_sequence())

        buttons = tk.Frame(self.root)
        buttons.pack(pady=8)

        tk.Button(
            buttons,
            text="Set Player Target",
            width=20,
            command=self.calibrate_target,
        ).grid(row=0, column=0, padx=5, pady=4)

        tk.Button(
            buttons,
            text="Calibrate Speed Coordinates",
            width=24,
            command=self.calibrate_playback_coordinates,
        ).grid(row=0, column=1, padx=5, pady=4)

        tk.Label(
            self.root,
            text=(
                f"Player target: {self.target_coord}    |    "
                f"Assumed speed: {PLAYBACK_SPEEDS[self.current_speed_index]}"
            ),
            fg="#475569",
            font=("Segoe UI", 8),
        ).pack(pady=4)

        tk.Label(
            self.root,
            text="Global shortcuts: O/P speed, N/T/W commands. Focus this window to enter numbers.",
            fg="#64748b",
            font=("Segoe UI", 8),
        ).pack(pady=(0, 10))

    def _bind_app_hotkeys(self) -> None:
        # Keep local bindings as a fallback when this window is focused.
        self.root.bind("<KeyPress>", self._handle_window_keypress)
        self.entry.bind("<KeyPress>", self._handle_entry_keypress, add="+")

    def _register_global_hotkeys(self) -> None:
        """Register shortcuts usable while Hudl/browser is the focused window."""
        try:
            for key in ("o", "p", "n", "t", "w", "x"):
                hotkey_id = keyboard.add_hotkey(
                    key,
                    lambda pressed_key=key: self._queue_global_hotkey(pressed_key),
                    suppress=True,
                    trigger_on_release=False,
                )
                self._global_hotkey_ids.append(hotkey_id)
            self.status.config(
                text="Global shortcuts active — keep Hudl focused. O/P speed; N/T/W commands.",
                fg="#15803d",
            )
        except Exception as error:
            self.status.config(
                text=f"Global shortcuts unavailable: {error}. Try running PowerShell as Administrator.",
                fg="#b45309",
            )

    def _queue_global_hotkey(self, key: str) -> None:
        # keyboard invokes callbacks outside Tk's UI thread.
        try:
            self.root.after(0, lambda: self._handle_global_hotkey(key))
        except tk.TclError:
            pass

    def _handle_global_hotkey(self, key: str) -> None:
        if self._global_action_running:
            return
        self._global_action_running = True
        try:
            if key in ("o", "p"):
                self._handle_speed_hotkey(key)
            elif key in ("n", "t", "w"):
                self.run_instant_command(key)
            elif key == "x":
                self._on_close()
        finally:
            self._global_action_running = False

    def _handle_entry_keypress(self, event):
        key = event.keysym.lower()
        if key in ("o", "p"):
            self._handle_speed_hotkey(key)
            return "break"
        if key in ("n", "t", "w"):
            self.run_instant_command(key)
            return "break"
        if key == "x":
            self._on_close()
            return "break"
        return None

    def _handle_window_keypress(self, event):
        key = event.keysym.lower()
        if key in ("o", "p"):
            self._handle_speed_hotkey(key)
            return "break"
        if key in ("n", "t", "w"):
            self.run_instant_command(key)
            return "break"
        if key == "x":
            self._on_close()
            return "break"
        return None

    def _handle_speed_hotkey(self, key: str) -> None:
        if key == "o":
            self.adjust_playback_speed(-1)
        elif key == "p":
            self.adjust_playback_speed(1)

    def _focus_entry(self) -> None:
        try:
            self.root.focus_force()
            self.entry.focus_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Tkinter coordinate capture overlays; clicks are saved to JSON
    # ------------------------------------------------------------------
    def _make_overlay(self, prompt: str) -> tuple[tk.Toplevel, tk.Label]:
        overlay = tk.Toplevel(self.root)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-alpha", 0.30)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black", cursor="crosshair")

        prompt_label = tk.Label(
            overlay,
            text=prompt,
            bg="#111827",
            fg="#4ade80",
            font=("Segoe UI", 16, "bold"),
            justify="left",
            padx=24,
            pady=18,
        )
        prompt_label.place(x=30, y=30)
        overlay.focus_force()
        return overlay, prompt_label

    def calibrate_target(self) -> None:
        self.overlay, label = self._make_overlay(
            "PLAYER TARGET CALIBRATION\n"
            "Click the Hudl player-selection box.\n"
            "Press Esc to cancel."
        )
        self.overlay.bind("<Button-1>", self._on_target_overlay_click)
        self.overlay.bind("<Escape>", lambda event: self._cancel_calibration())

    def _on_target_overlay_click(self, event) -> None:
        self.target_coord = (int(event.x_root), int(event.y_root))
        self._save_coordinates()
        self._destroy_overlay()
        self.status.config(
            text=f"Player target saved: {self.target_coord}",
            fg="#15803d",
        )
        self._clear_entry_without_focus()

    def calibrate_playback_coordinates(self) -> None:
        if self.overlay is not None:
            return

        self.calibration_index = 0
        self.overlay, self.calibration_label = self._make_overlay("")
        self.overlay.bind("<Button-1>", self._on_playback_overlay_click)
        self.overlay.bind("<Escape>", lambda event: self._cancel_calibration())
        self._update_calibration_prompt()

    def _update_calibration_prompt(self) -> None:
        if self.overlay is None:
            return

        key, description = CALIBRATION_STEPS[self.calibration_index]
        self.calibration_label.config(
            text=(
                f"PLAYBACK COORDINATE CALIBRATION "
                f"({self.calibration_index + 1}/{len(CALIBRATION_STEPS)})\n\n"
                f"Click: {description}\n"
                f"JSON key: {key}\n\n"
                "Each click is saved immediately. Press Esc to cancel."
            )
        )

    def _on_playback_overlay_click(self, event) -> None:
        key, description = CALIBRATION_STEPS[self.calibration_index]
        point = (int(event.x_root), int(event.y_root))
        self.playback_coords[key] = point
        self._save_coordinates()

        self.calibration_index += 1
        if self.calibration_index >= len(CALIBRATION_STEPS):
            self._destroy_overlay()
            self.status.config(
                text="All 7 playback coordinates saved to coordinates.json.",
                fg="#15803d",
            )
            self._clear_entry_without_focus()
            return

        self._update_calibration_prompt()

    def _cancel_calibration(self) -> None:
        self._destroy_overlay()
        self.status.config(
            text="Calibration cancelled. Coordinates already clicked were saved.",
            fg="#b45309",
        )
        self._clear_entry_without_focus()

    def _destroy_overlay(self) -> None:
        if self.overlay is not None:
            try:
                self.overlay.destroy()
            except tk.TclError:
                pass
            self.overlay = None

    # ------------------------------------------------------------------
    # O/P: playback speed control using saved screen coordinates
    # ------------------------------------------------------------------
    def adjust_playback_speed(self, direction: int) -> None:
        if self.overlay is not None:
            self.status.config(
                text="Finish or cancel coordinate calibration before using O/P.",
                fg="#b45309",
            )
            return

        base_index = (
            self.pending_speed_index
            if self.pending_speed_index is not None
            else self.current_speed_index
        )
        next_index = max(
            0,
            min(len(PLAYBACK_SPEEDS) - 1, base_index + direction),
        )

        if next_index == base_index:
            self.status.config(
                text=f"Already at {PLAYBACK_SPEEDS[base_index]} boundary.",
                fg="#b45309",
            )
            return

        self.pending_speed_index = next_index
        desired_speed = PLAYBACK_SPEEDS[next_index]

        # Cancel the previous idle-close timer on each new O/P press.
        if self._close_menu_after is not None:
            self.root.after_cancel(self._close_menu_after)
            self._close_menu_after = None

        # If a menu-opening/selection delay is already running, use the latest
        # requested speed rather than creating overlapping click sequences.
        if self._speed_select_after is not None:
            self.root.after_cancel(self._speed_select_after)
            self._speed_select_after = self.root.after(
                350, self._select_pending_speed
            )
            self.status.config(
                text=f"Changing playback speed to {desired_speed}...",
                fg="#334155",
            )
            return

        try:
            self.status.config(
                text=f"Opening speed menu for {desired_speed}...",
                fg="#334155",
            )
            self.root.update_idletasks()
            pyautogui.click(*self.playback_coords["menu"])
        except pyautogui.FailSafeException:
            self.pending_speed_index = None
            self.status.config(text="Speed change cancelled by PyAutoGUI fail-safe.", fg="red")
            self._clear_entry_without_focus()
            return
        except Exception as error:
            self.pending_speed_index = None
            self.status.config(text=f"Could not open speed menu: {error}", fg="red")
            self._clear_entry_without_focus()
            return

        self._speed_select_after = self.root.after(
            350, self._select_pending_speed
        )
        # Bring the Tkinter window back to the foreground so another O/P
        # press during the short selection delay is still received.
        self._clear_entry_without_focus()

    def _select_pending_speed(self) -> None:
        self._speed_select_after = None
        if self.pending_speed_index is None:
            return

        index = self.pending_speed_index
        speed = PLAYBACK_SPEEDS[index]

        try:
            pyautogui.click(*self.playback_coords[speed])
        except pyautogui.FailSafeException:
            self.pending_speed_index = None
            self.status.config(text="Speed selection cancelled by PyAutoGUI fail-safe.", fg="red")
            self._clear_entry_without_focus()
            return
        except Exception as error:
            self.pending_speed_index = None
            self.status.config(text=f"Could not select {speed}: {error}", fg="red")
            self._clear_entry_without_focus()
            return

        self.current_speed_index = index
        self.pending_speed_index = None
        self.status.config(
            text=(
                f"Playback speed set to {speed}. "
                "The close-menu action runs after 3 seconds of inactivity."
            ),
            fg="#15803d",
        )

        if self._close_menu_after is not None:
            self.root.after_cancel(self._close_menu_after)
        self._close_menu_after = self.root.after(
            3000, self._close_playback_menu
        )
        self._clear_entry_without_focus()

    def _close_playback_menu(self) -> None:
        self._close_menu_after = None
        try:
            # Use the configured close-menu point so this remains calibrated
            # to the user's Hudl layout.
            pyautogui.click(*self.playback_coords["exit_menu"])
            self.status.config(text="Playback menu close action completed.", fg="#334155")
        except pyautogui.FailSafeException:
            self.status.config(text="Close-menu action cancelled by PyAutoGUI fail-safe.", fg="red")
        except Exception as error:
            self.status.config(text=f"Could not close playback menu: {error}", fg="red")
        finally:
            self._clear_entry_without_focus()

    # ------------------------------------------------------------------
    # Existing instant commands N/T/W/X
    # ------------------------------------------------------------------
    def check_instant_keys(self, event) -> None:
        raw_input = self.entry.get().strip().lower()

        if raw_input == "x":
            self.entry.delete(0, tk.END)
            self.root.destroy()
            return

        if raw_input in ("n", "t", "w"):
            self.entry.delete(0, tk.END)
            self.run_instant_command(raw_input)

    def run_instant_command(self, key: str) -> None:
        self.status.config(text=f"Quick command: {key.upper()}", fg="#334155")
        self.root.update_idletasks()

        target_x, target_y = self.target_coord
        empty_y = target_y + 300

        try:
            pyautogui.click(target_x, empty_y)
            pyautogui.sleep(0.1)
            pyautogui.press(key)
            self.status.config(text=f"Quick command {key.upper()} sent.", fg="#15803d")
        except pyautogui.FailSafeException:
            self.status.config(text="Execution aborted by PyAutoGUI fail-safe.", fg="red")
        except Exception as error:
            self.status.config(text=f"Quick command failed: {error}", fg="red")
        finally:
            self._clear_entry_without_focus()

    # ------------------------------------------------------------------
    # Existing player-number + Enter block-tagging sequence
    # ------------------------------------------------------------------
    def run_complex_sequence(self) -> None:
        raw_input = self.entry.get().strip()
        if not raw_input:
            return

        players = raw_input.split()[:3]
        target_x, target_y = self.target_coord
        empty_y = target_y + 300

        self.status.config(
            text=f"Tagging players: {', '.join(players)}...",
            fg="#334155",
        )
        self.root.update_idletasks()

        try:
            pyautogui.click(target_x, empty_y)
            pyautogui.sleep(0.15)

            pyautogui.press("y")
            pyautogui.sleep(0.5)

            pyautogui.click(target_x, target_y)
            pyautogui.sleep(0.3)

            for player_num in players:
                pyautogui.write(player_num)
                pyautogui.sleep(0.15)
                pyautogui.press("tab")
                pyautogui.sleep(0.15)

            pyautogui.click(target_x, empty_y)
            pyautogui.sleep(0.3)
            pyautogui.press("e")

            self.status.config(
                text=f"Successfully tagged: {', '.join(players)}",
                fg="#15803d",
            )
        except pyautogui.FailSafeException:
            messagebox.showwarning(
                "FailSafe",
                "Mouse reached the screen corner. Check the target coordinates.",
                parent=self.root,
            )
            self.status.config(text="Execution aborted.", fg="red")
        except Exception as error:
            self.status.config(text=f"Tagging failed: {error}", fg="red")
        finally:
            self._clear_entry_without_focus()

    def _clear_entry_without_focus(self) -> None:
        """Clear the optional player-number entry without stealing Hudl focus."""
        try:
            self.entry.delete(0, tk.END)
        except tk.TclError:
            pass

    def _on_close(self) -> None:
        for hotkey_id in self._global_hotkey_ids:
            try:
                keyboard.remove_hotkey(hotkey_id)
            except Exception:
                pass
        self._global_hotkey_ids.clear()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


if __name__ == "__main__":
    root = tk.Tk()
    app = InteractiveHudlTagger(root)
    root.mainloop()
