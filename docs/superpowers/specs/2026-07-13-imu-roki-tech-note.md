# Rokid Glass 2 IMU 数据获取与回传技术说明

**日期**: 2026-07-13

## 1. 现状

Rokid CXR-L / CXR-S 当前 SDK 版本均不暴露 IMU 接口。但眼镜运行 Android 系统，
可通过 Android SensorManager 获取加速度计和陀螺仪数据。

## 2. 技术方案：眼镜端 SensorManager + CXR 通道回传

### 2.1 架构

眼镜端（MainActivity）:
  - 注册 SensorManager.TYPE_ACCELEROMETER 和 TYPE_GYROSCOPE
  - 采样频率: SENSOR_DELAY_GAME (50Hz)
  - 每条数据封装为 Caps 数组: [imu, ax, ay, az, gx, gy, gz, timestamp]
  - 通过 bridge.sendMessage(rk_custom_key, caps) 发送到手机

手机端（CxrGlassesConnection）:
  - 在 customCmdCallback.onCustomCmdResult() 中解析 IMU 数据
  - 新增 IMU Flow 暴露给 RecordingController
  - 时间戳 System.currentTimeMillis() 与照片帧对齐

### 2.2 坐标系

Android 传感器标准坐标系:
  x: 手机/眼镜右侧（短边）
  y: 手机/眼镜上方（长边）
  z: 屏幕/镜片外侧

注意: 眼镜佩戴时传感器方向与头部朝向一致，需根据实际佩戴校准。

### 2.3 数据量估算

每条 IMU 数据: ~7 float + 1 long = 32 bytes
@50Hz = 1.6 KB/s
CXR Caps 通道完全可以承载

### 2.4 手机端集成点

CxrGlassesConnection 新增:
  - imuFlow: SharedFlow<ImuSample>
  - 在 customCmdCallback 中解析 imu 前缀的 Caps

RecordingController.startSpace() 新增:
  - 收集 imuFlow 数据
  - 实时估算位姿（dead reckoning）
  - 上传 IMU 数据到后台（与照片一起用于 3DGS 重建）

### 2.5 视角覆盖算法（MVP）

位姿追踪: 基于 IMU 积分 + 照片关键帧的视觉特征，估算当前相机 6DOF 位姿
覆盖判断: 将相机位置（球面坐标 θ, φ）离散化为网格，标记已覆盖的格子
引导提示: 根据未覆盖区域给出方向指示

## 3. 眼镜端代码示意

class MainActivity : AppCompatActivity() {
    private lateinit var sensorManager: SensorManager
    private var accel: Sensor? = null
    private var gyro: Sensor? = null

    fun startImuCapture() {
        accel = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        gyro = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
        sensorManager.registerListener(imuListener, accel, SENSOR_DELAY_GAME)
        sensorManager.registerListener(imuListener, gyro, SENSOR_DELAY_GAME)
    }

    private val imuListener = object : SensorEventListener {
        var lastAx=0f; var lastAy=0f; var lastAz=0f
        var lastGx=0f; var lastGy=0f; var lastGz=0f
        override fun onSensorChanged(event: SensorEvent) {
            when (event.sensor.type) {
                Sensor.TYPE_ACCELEROMETER -> { lastAx=event.values[0]; lastAy=event.values[1]; lastAz=event.values[2] }
                Sensor.TYPE_GYROSCOPE -> { lastGx=event.values[0]; lastGy=event.values[1]; lastGz=event.values[2] }
            }
            val caps = Caps().apply {
                write(imu)
                write(lastAx); write(lastAy); write(lastAz)
                write(lastGx); write(lastGy); write(lastGz)
                write(System.currentTimeMillis().toString())
            }
            bridge.sendMessage(rk_custom_key, caps)
        }
        override fun onAccuracyChanged(sensor: Sensor, accuracy: Int) {}
    }
}

## 4. 手机端解析示意

// 在 CxrGlassesConnection.customCmdCallback.onCustomCmdResult() 中:
if (key == rk_custom_key && tokens[0] == imu) {
    val sample = ImuSample(
        ax = tokens[1].toFloat(), ay = tokens[2].toFloat(), az = tokens[3].toFloat(),
        gx = tokens[4].toFloat(), gy = tokens[5].toFloat(), gz = tokens[6].toFloat(),
        timestampMs = tokens[7].toLong(),
    )
    _imuFlow.tryEmit(sample)
    return  // 不触发 START/STOP 解析
}

## 5. 风险与限制

1. SensorManager 在 Rokid Glass 2 上是否完全可用需实测验证
2. IMU 积分漂移: 纯 IMU dead reckoning 会在几秒内累积误差，需结合视觉特征校正
3. CXR 通道容量: 50Hz 持续发送可能影响照片和音频传输带宽
4. 眼镜端持续传感器采集会增加功耗
