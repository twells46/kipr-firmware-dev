## Summary

Builds on @chrehall68's #6, which rewrites the MPU9250 driver against a proper register map and replaces the hand-rolled `IMU_write(0x25, ...)` sequences with named helpers. This PR carries that work forward and makes `readIMU()` fit the main loop's timing budget.

## Changes on top of #6

- **Remove ~1.98 ms of blocking delay from `readIMU()`.** `ACCEL_*OUT`/`GYRO_*OUT` are latched by the MPU9250 at the configured sample rate, so no settling delay is needed between the two reads. `main()` only has a ~700 µs coasting window before it must sample motor back-EMF — blocking there stretched the loop and jittered PID timing.
- **Rebase onto `master`'s formatting.** #6 reformatted `main.c` wholesale; this keeps upstream style so the diff shows only the IMU changes.

## Carried from #6

- `Firmware/include/mpu9250regmap.h` — MPU9250/AK8963 register map (credit: [hideakitai/MPU9250](https://github.com/hideakitai/MPU9250)).
- `readIMU(uint32_t count)` self-schedules: accel/gyro at ~200 Hz, magnetometer at ~100 Hz.
- Drops the duplicate `setupIMU()` call from `main()` (`wallaby_init.c:311` already calls it).
- Removes the dead `setupAccelMag`/`setupGyro`/`readAccel`/`readMag`/`readGyro` declarations.

## Known issues (inherited from #6, not fixed here)

- `setup_magnetometer()` indexes `raw_data[0]` instead of `raw_data[i]`, so all three axes get X's sensitivity.
- `magn_scale_factors` is computed but never applied — magnetometer values go to `aTxBuffer` unscaled, and `MPU9250_MAGN_SENS_SCALING` is now unused.

## Testing

Clang syntax check clean. **Not yet flashed to hardware** — the delay removal needs on-device verification that accel/gyro reads stay coherent.
