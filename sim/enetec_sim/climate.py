"""Plausible room-climate series for the measurement fields of samples/telemetry.json.

Only meant to make payloads look and evolve realistically: radiant heating is
slow, setpoints drop at night, occupancy drives CO2 and humidity. It is not a
model of ENETEC devices and must not be used to derive product behaviour.
"""
import math
from datetime import datetime, timezone


def _smooth(a, b, x):
    x = min(max((x - a) / (b - a), 0.0), 1.0)
    return x * x * (3 - 2 * x)


def occupancy(plant_type, hour, weekday):
    if plant_type == 'commercial':
        if weekday >= 5:
            return 0.05
        lunch = 1.0 - 0.4 * _smooth(12.0, 12.5, hour) * (1.0 - _smooth(13.0, 13.5, hour))
        return _smooth(7.0, 9.0, hour) * (1.0 - _smooth(17.0, 19.0, hour)) * lunch
    away = 0.0 if weekday >= 5 else _smooth(7.5, 8.5, hour) * (1.0 - _smooth(16.5, 18.0, hour))
    return 1.0 - 0.8 * away


def setback(plant_type, hour, weekday):
    """True while the comfort setpoint is lowered (night / closed building)."""
    if plant_type == 'commercial':
        return weekday >= 5 or not 6.0 <= hour < 19.0
    return hour >= 22.5 or hour < 5.5


class RoomClimate:
    TEMP_TAU_S = 3 * 3600.0     # radiant systems react slowly
    CO2_TAU_S = 1200.0
    SETBACK_C = 2.0

    def __init__(self, params, plant_type, outdoor_co2_ppm, utc_offset_h, rng):
        self.p, self.plant_type = params, plant_type
        self.outdoor = outdoor_co2_ppm
        self.offset_s = utc_offset_h * 3600
        self.rng = rng
        self.temp = self.co2 = self.last = None

    def sample(self, epoch_s):
        local = datetime.fromtimestamp(epoch_s + self.offset_s, tz=timezone.utc)
        hour = local.hour + local.minute / 60 + local.second / 3600
        occ = occupancy(self.plant_type, hour, local.weekday()) * self.p['occupancy']
        target = self.p['setpoint_c'] + 0.5 * occ
        if setback(self.plant_type, hour, local.weekday()):
            target -= self.SETBACK_C
        co2_target = self.outdoor + occ * self.p['co2_gain_ppm']
        if self.last is None:
            self.temp, self.co2 = target, co2_target
        else:
            dt = max(epoch_s - self.last, 0.0)
            self.temp += (target - self.temp) * (1 - math.exp(-dt / self.TEMP_TAU_S))
            self.co2 += (co2_target - self.co2) * (1 - math.exp(-dt / self.CO2_TAU_S))
        self.last = epoch_s
        rh = self.p['base_rh_pct'] - 1.8 * (self.temp - self.p['setpoint_c']) + 5.0 * occ
        return {
            'temperatureC': round(self.temp + self.rng.gauss(0, 0.05), 1),
            'humidityPct': round(min(max(rh + self.rng.gauss(0, 0.3), 15.0), 85.0), 1),
            'co2Ppm': int(round(max(self.co2 + self.rng.gauss(0, 8), self.outdoor - 20))),
        }
