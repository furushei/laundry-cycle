from m5stack import lcd, buttonA, buttonC, speaker
from machine import Timer
import time


# State definitions
ST_IDLE = 1
ST_WASHING = 2
ST_NOTIFYING = 3
ST_UNLOADING = 4

# UI settings
BACKGROUND_COLOR_IDLE = 0x808080
BACKGROUND_COLOR_WASHING = 0x6666FF
BACKGROUND_COLOR_NOTIFYING = 0xFF8000
BACKGROUND_COLOR_UNLOADING = 0x009900

STATE_TEXT_COLOR = 0xFFFFFF
LABEL_TEXT_COLOR = 0xFFFFFF

BUTTON_FILL_COLOR = 0xE6E6E6
BUTTON_TEXT_COLOR = 0x808080

# Beep settings
BEEP_VOLUME = 2
BEEP_FREQUENCY = 1000  # Hz
BEEP_DURATION = 200    # ms
BEEP_PERIOD = 2000    # ms

# Washing machine settings
WASHING_DURATION = 30 * 60    # seconds


def format_time(seconds):
    minutes = seconds // 60
    secs = seconds % 60
    return "{:02d}:{:02d}".format(int(minutes), int(secs))


def draw_state(state_text, color, background_color):
    lcd.setwin(0, 40, 320, 120)
    lcd.set_bg(background_color)
    lcd.text(lcd.CENTER, lcd.CENTER, state_text, color)
    lcd.resetwin()


def draw_label(label_text, color, background_color):
    lcd.setwin(0, 120, 320, 160)
    lcd.set_bg(background_color)
    lcd.text(lcd.CENTER, lcd.CENTER, label_text, color)
    lcd.resetwin()


def draw_button(button, label=None):
    if button not in ['a', 'b', 'c']:
        return
    if button == 'a':
        x1, y1, x2, y2 = 30, 200, 100, 240
    elif button == 'b':
        x1, y1, x2, y2 = 125, 200, 195, 240
    elif button == 'c':
        x1, y1, x2, y2 = 220, 200, 290, 240
    
    lcd.setwin(x1, y1, x2, y2)
    lcd.clearwin(BUTTON_FILL_COLOR)
    if label:
        lcd.set_bg(BUTTON_FILL_COLOR)
        lcd.text(lcd.CENTER, lcd.CENTER, label, BUTTON_TEXT_COLOR)
    lcd.resetwin()


def draw_idle_screen():
    lcd.clear(BACKGROUND_COLOR_IDLE)
    draw_state("IDLE", STATE_TEXT_COLOR, BACKGROUND_COLOR_IDLE)
    draw_button('a', 'RESET')
    draw_button('b', '')
    draw_button('c', 'START')


def draw_remaining_time(remaining_time):
    time_text = format_time(remaining_time)
    draw_label(time_text, LABEL_TEXT_COLOR, BACKGROUND_COLOR_WASHING)


def draw_washing_screen(remaining_time=None):
    lcd.clear(BACKGROUND_COLOR_WASHING)
    draw_state("WASHING", STATE_TEXT_COLOR, BACKGROUND_COLOR_WASHING)
    if remaining_time is not None:
        draw_remaining_time(remaining_time)
    draw_button('a', 'RESET')
    draw_button('b', '')
    draw_button('c', 'SKIP')


def draw_notifying_screen():
    lcd.clear(BACKGROUND_COLOR_NOTIFYING)
    draw_state("NOTIFYING", STATE_TEXT_COLOR, BACKGROUND_COLOR_NOTIFYING)
    draw_button('a', 'RESET')
    draw_button('b', '')
    draw_button('c', 'STOP')


def draw_unloading_screen():
    lcd.clear(BACKGROUND_COLOR_UNLOADING)
    draw_state("UNLOADING", STATE_TEXT_COLOR, BACKGROUND_COLOR_UNLOADING)
    draw_button('a', 'RESET')
    draw_button('b', '')
    draw_button('c', 'END')


def get_remaining_time(start_time):
    elapsed_time = time.time() - start_time
    remaining_time = max(0, WASHING_DURATION - elapsed_time)
    return remaining_time


def beep(timer):
    speaker.volume(BEEP_VOLUME)
    speaker.tone(BEEP_FREQUENCY, BEEP_DURATION)


timer = None

def start_beep():
    global timer
    if timer is None:
        timer = Timer(0)
        timer.init(period=BEEP_PERIOD, mode=Timer.PERIODIC, callback=beep)


def stop_beep():
    global timer
    if timer is not None:
        timer.deinit()
        timer = None


def start():
    lcd.clear()

    state = ST_IDLE
    start_time = None

    draw_idle_screen()

    while True:
        # update state
        if state == ST_IDLE:
            if buttonC.isPressed():
                while buttonC.isPressed():
                    pass  # wait for button release
                state = ST_WASHING
                draw_washing_screen()
                start_time = time.time()
        elif state == ST_WASHING:
            if buttonA.isPressed():
                while buttonA.isPressed():
                    pass  # wait for button release
                state = ST_IDLE
            elif buttonC.isPressed():
                while buttonC.isPressed():
                    pass  # wait for button release
                state = ST_NOTIFYING
                start_beep()
                draw_notifying_screen()
            elif get_remaining_time(start_time) <= 0:
                state = ST_NOTIFYING
                start_beep()
                draw_notifying_screen()
            else:
                draw_remaining_time(get_remaining_time(start_time))
        elif state == ST_NOTIFYING:
            if buttonA.isPressed():
                while buttonA.isPressed():
                    pass  # wait for button release
                state = ST_IDLE
                stop_beep()
                draw_idle_screen()
            elif buttonC.isPressed():
                while buttonC.isPressed():
                    pass  # wait for button release
                state = ST_UNLOADING
                stop_beep()
                draw_unloading_screen()
        elif state == ST_UNLOADING:
            if buttonA.isPressed():
                while buttonA.isPressed():
                    pass  # wait for button release
                state = ST_IDLE
                draw_idle_screen()
            elif buttonC.isPressed():
                while buttonC.isPressed():
                    pass  # wait for button release
                state = ST_IDLE
                draw_idle_screen()
        time.sleep(0.1)
