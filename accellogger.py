from array import array
from machine import I2C
import _thread
import time
import uos

import mpu9250


# Sampling settings
SAMPLE_PERIOD = 10           # ms (about 100Hz)
RING_BUFFER_SIZE = 3000      # samples (SAMPLE_PERIOD * 3000 = about 30 seconds)

# I2C settings (M5Stack internal I2C bus)
I2C_SDA = 21
I2C_SCL = 22

# SD card settings
LOG_DIR = '/sd/accel'
CSV_HEADER = 'ticks_ms,state,x,y,z\n'
FLUSH_PERIOD = 1000          # ms
DUMP_CHUNK_ROWS = 200        # rows per write while dumping the ring buffer

# Thread settings
THREAD_STACK_SIZE = 8192     # bytes


# Pre-trigger ring buffer (filled only while in the idle state,
# preallocated to avoid fragmenting the heap later)
_ring_ticks = array('L', (0 for _ in range(RING_BUFFER_SIZE)))
_ring_x = array('f', (0 for _ in range(RING_BUFFER_SIZE)))
_ring_y = array('f', (0 for _ in range(RING_BUFFER_SIZE)))
_ring_z = array('f', (0 for _ in range(RING_BUFFER_SIZE)))
_ring_index = 0    # next position to write
_ring_count = 0    # number of valid samples

_imu = None
_state = 0         # current app state, written by the main thread only
_idle_state = 0    # state value that means "buffer only, do not record"


def init(idle_state):
    global _imu, _state, _idle_state
    _idle_state = idle_state
    _state = idle_state
    try:
        i2c = I2C(0, sda=I2C_SDA, scl=I2C_SCL)
        _imu = mpu9250.MPU9250(i2c)
        _imu.acceleration  # test read
    except Exception:
        return False
    try:
        _mount_sd()
        uos.mkdir(LOG_DIR)
    except OSError:
        pass  # LOG_DIR already exists, or SD missing (checked below)
    except Exception:
        return False
    try:
        uos.listdir(LOG_DIR)
    except Exception:
        return False
    _start_thread()
    return True


def set_state(state):
    # a single int store is atomic under the GIL, so no lock is needed
    global _state
    _state = state


def _mount_sd():
    try:
        uos.mountsd()
    except Exception:
        # already mounted, or firmware without mountsd(); verified by
        # the LOG_DIR check in init()
        pass


def _start_thread():
    try:
        _thread.stack_size(THREAD_STACK_SIZE)
    except Exception:
        pass
    try:
        # the loboris fork takes a thread name as the first argument
        _thread.start_new_thread('accellogger', _thread_main, ())
    except TypeError:
        _thread.start_new_thread(_thread_main, ())


def _next_file_path():
    last = 0
    for name in uos.listdir(LOG_DIR):
        if not name.endswith('.csv'):
            continue
        try:
            number = int(name[:-4])
        except ValueError:
            continue
        if number > last:
            last = number
    return '{}/{:04d}.csv'.format(LOG_DIR, last + 1)


def _format_row(ticks, state, x, y, z):
    return '{},{},{:.4f},{:.4f},{:.4f}\n'.format(ticks, state, x, y, z)


def _push_ring(ticks, x, y, z):
    global _ring_index, _ring_count
    _ring_ticks[_ring_index] = ticks
    _ring_x[_ring_index] = x
    _ring_y[_ring_index] = y
    _ring_z[_ring_index] = z
    _ring_index = (_ring_index + 1) % RING_BUFFER_SIZE
    _ring_count = min(_ring_count + 1, RING_BUFFER_SIZE)


def _dump_ring_buffer(file):
    # runs inside the logger thread, which is the only reader and
    # writer of the ring buffer, so no locking is needed
    global _ring_index, _ring_count
    if _ring_count < RING_BUFFER_SIZE:
        start = 0
    else:
        start = _ring_index
    rows = []
    for offset in range(_ring_count):
        i = (start + offset) % RING_BUFFER_SIZE
        rows.append(_format_row(
            _ring_ticks[i], _idle_state, _ring_x[i], _ring_y[i], _ring_z[i]))
        if len(rows) >= DUMP_CHUNK_ROWS:
            file.write(''.join(rows))
            rows = []
    if rows:
        file.write(''.join(rows))
    _ring_index = 0
    _ring_count = 0


def _thread_main():
    file = None
    pending = []
    last_flush = time.ticks_ms()
    deadline = time.ticks_ms()
    while True:
        deadline = time.ticks_add(deadline, SAMPLE_PERIOD)
        state = _state
        try:
            ticks = time.ticks_ms()
            x, y, z = _imu.acceleration
            if state == _idle_state:
                if file:
                    file.write(''.join(pending))
                    pending = []
                    file.close()
                    file = None
                _push_ring(ticks, x, y, z)
            else:
                if file is None:
                    file = open(_next_file_path(), 'w')
                    file.write(CSV_HEADER)
                    _dump_ring_buffer(file)
                    last_flush = time.ticks_ms()
                    deadline = time.ticks_ms()  # dumping takes a while
                pending.append(_format_row(ticks, state, x, y, z))
                if time.ticks_diff(time.ticks_ms(), last_flush) >= FLUSH_PERIOD:
                    file.write(''.join(pending))
                    pending = []
                    file.flush()
                    last_flush = time.ticks_ms()
        except Exception:
            # SD or IMU failure: stop logging only, the app keeps running
            if file:
                try:
                    file.close()
                except Exception:
                    pass
            return
        remaining = time.ticks_diff(deadline, time.ticks_ms())
        if remaining > 0:
            time.sleep_ms(remaining)
        else:
            deadline = time.ticks_ms()  # resync after a long stall
