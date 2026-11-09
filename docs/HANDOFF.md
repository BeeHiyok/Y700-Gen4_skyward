# Skyward → Lenovo LEGION Y700 四代 / TB322FC 移植交接文档

> 本文写给接手修复的其他 agent。目标是把当前进度、所有已验证事实、失败路径、源码改动、镜像哈希、复现方法、回滚方法和剩余问题完整交接。  
> 当前时间基准：2026-11-08。当前工作目录：`I:\rec移植`。设备已接入，有 root/su，bootloader 解锁。

---

## 0. 一句话现状

**当前最稳定且设备上正在运行的是 v3.7。**

- UI/触控框架、adb、MTP、USB、命令重启、中文设备名、CPU 显示 4.32GHz 均已修好。
- **熄屏背光已真正熄灭**（亮度降到 1/4095，视觉全黑），且**熄屏不掉 USB**。
- 关键：v3.3 及以前"背光关不掉"和"熄屏掉 USB"是两个独立的 bug，v3.7 都已定位并修复；根因见第 15 节。
- data 解密、WLAN、振动仍未完成；v4/v5 的服务链/WLAN/haptics 实验会造成服务崩溃、黑屏循环和掉 USB，不要沿用。

当前稳定镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-v37-stable-slot-b.img
SHA-256 36c0b121827add264c506b62bfc11b3e6c3d418c991be2238aeb7db2edbea96a
size 104857600
```

当前稳定 binary：

```text
I:\rec移植\official-payload\system\bin\recovery-v37
SHA-256 fb211bf410c32cf971c3f5528ed17a26189e0a8e1216b5784fd63cb7f4fa4e11
```

当前稳定配置：

```text
I:\rec移植\devices\TB322FC-stable.toml
SHA-256 3552419ef58f4296300fd86e6fabd9b5ebf81499ffa94c482e89d6fc3cd63b7d
```

---

## 1. 设备与平台事实

### 1.1 身份

- 型号：`Lenovo TB322FC_PRC / TB322FC`
- 市场名：`联想拯救者Y700（第四代）`
- 平台：Qualcomm `sun` / SM8750，`ro.board.platform=sun`
- 当前系统：Android 16，`ZUXOS_1.5.10.294_260714_PRC`
- 内核：`6.6.118-android15-8-g350f378eb496-ab14943902-4k`
- 当前槽：`_b`
- A/B：是
- bootloader：`unlocked`，`verifiedbootstate=orange`
- root：有，`/system/bin/su`，KernelSU 环境 `u:r:ksu:s0`

### 1.2 分区

重要分区均为完整 100 MiB/96 MiB 等整分区 dump，位于：

```text
I:\rec移植\device-backup\
```

关键哈希：

```text
recovery_a.img  30763f4efdfe8e828240362b58d1a432224349d1ab819ef0cd2bb317c482279a  # 原厂 AOSP recovery
recovery_b.img  8e2d247e26c2439ae27cad242d6e5d57e4743a4763f6a3da0f77a41017383fbe  # 设备原有 TWRP
```

`recovery_a.img` 是联想原厂 AOSP recovery（Android 15 / SDK35 ramdisk）。  
`recovery_b.img` 是当前槽原有的 TWRP（`twrp_elden-eng 16.1.0 BP2A.250605.031.A2`，Android 16 / SDK36 ramdisk），并**不是原厂 recovery**。

A/B recovery 分区大小：

```text
0x6400000 = 104857600 bytes
```

所有生成的镜像都是 104,857,600 字节整分区，尾部有 Skyward 生成的 `AVBf + AVB0 algorithm NONE` footer；boot header 为 v4，`kernel_size=0`，ramdisk 为 LZ4-legacy compressed cpio newc。

完整备份哈希清单：

```text
I:\rec移植\device-backup\SHA256SUMS.txt
```

### 1.3 屏幕 / 触控 / 背光 / CPU

- 屏幕物理：`1904×3040`，density `440`，对角 `8.8`，圆角 `55`
- DRM：`/dev/dri/card0`，connector `card0-DSI-1`，modes 含 `1904x3040x120vid`、`1904x3040x165vid` 等
- panel 名称：`qcom,mdss_dsi_elden_nt36523_csot_3k_dsc_vid`
- panel DT 属性：
  - `qcom,mdss-brightness-max-level = 4095`
  - `qcom,mdss-dsi-bl-max-level = 4095`
  - `/sys/class/backlight/panel0-backlight/max_brightness = 4095`
- 背光节点：
  - `/sys/class/backlight/panel0-backlight/brightness`
  - `/sys/class/backlight/panel0-backlight/actual_brightness`
  - `/sys/class/backlight/panel0-backlight/bl_power`
  - `bl_power=0` 亮屏允许，`4` 为 `FB_BLANK_POWERDOWN`
- DSI panel 状态节点（只读）：
  - `/sys/devices/platform/soc/ae00000.qcom,mdss_mdp/drm/card0/sde-conn-2-DSI-1/panel_power_state`
- 触控：
  - `NVTCapacitiveTouchScreen`，direct multitouch
  - ABS X `0..19040`，ABS Y `0..30400`
- 振动：
  - 两个 `aw-haptic-hv` FF 输入设备
  - `/sys/devices/virtual/misc/aw8697_haptic_l`, `aw8697_haptic_r`
  - 无 Skyward 原用的 `resonance` 频率文件
- CPU：
  - `possible/present = 0-7`
  - `policy0` CPU0–5 max `3532800 kHz`
  - `policy6` CPU6–7 max `4320000 kHz`
  - UI 期望显示 `4.32GHz`，不是 8.64GHz

---

## 2. 源码与构建环境

### 2.1 源码

工作区源码：

```text
I:\rec移植\skyward
```

上游版本：`v0.2.0`，HEAD `22528ba chore: release 0.2.0`。  
官方 release 使用 `skyward-v0.2.0-nezha-OS4.0.4.0.XPACNXM.zip`，其 SHA-256 已与 `SHA256SUMS` 对齐：

```text
d79f9fe78b019324bf0ceb2b26516e5aafb594fbf102b6947ad3f6a68b603454
```

官方 zip 解压出的通用 arm64 资源：

```text
I:\rec移植\official-payload\system\bin\recovery
SHA-256 8ed419967c38ad10b96cdc49ad9c1c6ff925030cb666eb563f50134f261d7350
I:\rec移植\official-payload\skyward\system-init
SHA-256 cccb180e5e29bde7a834a4832962975336f324a09392bf294f64fe533cb7ff5e
```

字体、OFL、task_profiles、mtp.rc 等也在 `official-payload`。

### 2.2 WSL Ubuntu 工具链

设备所在 Windows 机器安装了 WSL Ubuntu 26.04：

```bash
wsl -d Ubuntu -u root
```

已安装：

- `cargo`, `rustc`, `rustup stable 1.99.1`
- Android NDK r29：`/opt/android-ndk-r29`
- `cargo-ndk 4.1.2`
- `lz4`, `zip`, `unzip`, `python3`, `git`, `curl`
- Rust Android std 从 Windows rustup 目录复制到 WSL sysroot：
  - Windows 源：`C:\Users\zhanr\.rustup\toolchains\stable-x86_64-pc-windows-msvc\lib\rustlib\aarch64-linux-android`
  - WSL 目标：`/root/.rustup/toolchains/stable-x86_64-unknown-linux-gnu/lib/rustlib/aarch64-linux-android`

因为 `rust-toolchain.toml` 会触发 rustup 联网安装 Android target 且网络不稳定，编译脚本会临时把 `rust-toolchain.toml` 改成：

```toml
[toolchain]
channel = "stable"
```

并用：

```bash
export RUSTUP_TOOLCHAIN=stable-x86_64-unknown-linux-gnu
export RUSTFLAGS="--sysroot /root/.rustup/toolchains/stable-x86_64-unknown-linux-gnu"
export CARGO_TARGET_DIR=/tmp/skyward-android-target
export ANDROID_NDK_HOME=/opt/android-ndk-r29
export PATH="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin:$HOME/.cargo/bin:$PATH"
cargo ndk -t arm64-v8a --platform 30 build --locked --release -p skyward
```

编译后 trap 恢复 `rust-toolchain.toml`。所有 v3.x/v4/v5 binary 都是这样产出的。

### 2.3 主机打包工具

- 官方 packer 原生 Linux 版：`I:\rec移植\skyward-pack-linux`
- Python 独立解析/打包工具：`I:\rec移植\port_tool.py`
  - 支持 Android boot header v3/v4
  - LZ4-legacy decode/encode（编码用 WSL `lz4 -l -12 --favor-decSpeed -c` 代替，避免自写编码器边界问题）
  - cpio newc decode/encode
  - AVBf/AVB0 hash footer 生成
- 主要打包脚本：
  - `make-v3.sh`, `make-v31.sh`, `make-v32.sh`, `make-v33.sh`, `make-v34.sh`
  - `make-v5.sh`
  - `port_tool.py`
  - `verify-v2.py`, `verify-image.py`, `make-slot-b.sh`

常用打包方式：从已验证的 v3 或 v3.x 镜像读取 ramdisk，只替换：

```text
system/bin/recovery
skyward/device.toml
```

然后重新 `cpio_encode` → WSL `lz4 -l -12 --favor-decSpeed -c` → 通过 `port_tool.avb_footed()` 生成整分区镜像。

---

## 3. 当前工作区源码状态

`git status --short`：

```text
 M crates/skyward-binder/src/parcel.rs
 M crates/skyward-config/src/lib.rs
 M crates/skyward-info/src/lib.rs
 M crates/skyward-modules/src/lib.rs
 M crates/skyward-sys/src/lib.rs
 M crates/skyward-ui/src/surface.rs
 M crates/skyward/src/haptics.rs
 M crates/skyward/src/ui.rs
?? devices/TB322FC.toml
```

`git diff --stat`：

```text
 crates/skyward-binder/src/parcel.rs | 11 +++--
 crates/skyward-config/src/lib.rs    | 39 ++++++++++++++---
 crates/skyward-info/src/lib.rs      |  8 +++-
 crates/skyward-modules/src/lib.rs   | 31 ++++++++++----
 crates/skyward-sys/src/lib.rs       | 49 +++++++++++++++++++++-
 crates/skyward-ui/src/surface.rs    | 84 +++++++++++++++++++++----------------
 crates/skyward/src/haptics.rs       |  7 +++-
 crates/skyward/src/ui.rs            | 32 ++++++++++++--
 8 files changed, 201 insertions(+), 60 deletions(-)
```

### 重要：工作区源码 ≠ 当前稳定镜像

当前工作区源码包含大量 v4/v5 实验改动，且现在最后停留在 **v3.4**（DPMS-only 熄屏）源码状态。当前设备刷入/运行的是 **v3.3** binary，二者的 source state 不同。

接手时务必注意：

- 当前稳定配置是 `devices/TB322FC-stable.toml`，不含服务/WLAN/haptics。
- `skyward/devices/TB322FC.toml` 是实验配置，含中文名、CPU、服务/WLAN/haptics 等历史改动，**不是稳定基线**。
- 若要从源码复现稳定 v3.3，需要把工作区源码回退/分拣到 v3.3 对应状态，不要直接 `cargo ndk build` 当前工作区。

---

## 4. 版本历史、哈希与结论

所有镜像均为 `104857600` 字节，均只刷/测试过当前 `_b` 槽的 `recovery_b`（除非脚本明确双槽）。

### 4.1 v1（失败）

镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-ZUXOS_1.5.10.294.img
SHA-256 524f9aaadc08e4720345d261ed1251c3e11a72d46df2e114b5749ca15671005b
```

另有 B 槽 `modem_b` fstab 修正：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-ZUXOS_1.5.10.294-slot-b.img
SHA-256 2c74ce4c4982adb2a5f8933be0717d2d5727c7c234f13932757a530a7d2fae5e
```

基底：`device-backup/recovery_a.img`（原厂 Android15 ramdisk）。  
失败：当前系统 `_b` 是 Android16/vendor_boot 环境，v1 重启后卡联想/开机图标，adb 和 fastboot 都不枚举。已回滚。

教训：**不要用 A 槽原厂 Android15 ramdisk 给 Android16 B 槽打包**。

### 4.2 v2（失败，但有诊断价值）

镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-v2-twrpbase-slot-b.img
SHA-256 850d254e68f9961163edd3ef480df4b7a173a3888ae74a2dd08feb5e6fc03f6e
```

基底：`device-backup/recovery_b.img`（当前可启动 TWRP Android16 ramdisk）。  
保留 TWRP init/USB/SPU 环境，替换 `system/bin/recovery`。  
结果：adb/USB 能起，但黑屏。日志：

```text
recovery failed: panel qcom,mdss_dsi_elden_nt36523_csot_3k_dsc_vid gives its normal maximum as none of [...]
```

根因：`Backlight::open()` → `normal_max()` 只认三套小米 DT 属性，联想 `elden` panel 没有这些属性，Skyward 在打开 KMS/UI 前主动退出。

### 4.3 v3（首次成功点亮）

镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-v3-twrpbase-slot-b.img
SHA-256 ff81c099183cc66c816245b82b535221a662cd110044d5f479d5b62d951a8ed0
binary I:\rec移植\official-payload\system\bin\recovery-v3
SHA-256 ae35a1a60522133b43338faff9404898c3cc9f90d3ab5ffaac56c35ba4a9f57c
```

修复：`crates/skyward/src/ui.rs` 的 `NORMAL_MAX` 增加：

```rust
("qcom,mdss-brightness-max-level", "qcom,mdss-dsi-bl-max-level"),
```

设备 DT 实测两个值都是 4095，和 `/sys/class/backlight/panel0-backlight/max_brightness` 一致。  
实机：Skyward UI 点亮，adb/MTP/USB 正常，DRM 1904×3040 正常。

v3 配置仍是英文型号，且没有 CPU 显示修正、命令重启修正、bl_power 熄屏修正。

### 4.4 v3.1（稳定修复阶段 1）

镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-v31-stable-slot-b.img
SHA-256 4d206946d78f2a3446131b13e9fbe382e8b9581630105f292479cb8976843620
binary I:\rec移植\official-payload\system\bin\recovery-v31
SHA-256 e1a5f081017d3dc46cc812917ea59a8e4138a46a925460369791a898cd09774a
```

新增：

1. 中文型号：
   ```text
   联想拯救者Y700（第四代）
   ```
2. CPU 显示修正：
   - 新增 `[cpu] max_khz = 4320000`
   - `skyward-config` 新增 `CpuConfig`
   - `skyward-info::collect()` 用配置覆盖 `Cpu.max_khz`
   - 不改实际 CPU 频率/调度
   - 原因：用户截图 UI 曾显示 `八核 最高 8.64GHz`，而 sysfs/CLI `info` 一直是 `4320000 kHz / 4.32GHz`
3. 命令重启修复：
   - `skyward_sys::power()` 先尝试 `sys.powerctl`
   - TWRP/Android16 init 拒绝后写 BCB（`boot-recovery` / `boot-fastboot`）并调用 raw Linux `reboot(2)` syscall
   - `system` 清 BCB 后 `RB_AUTOBOOT`，`off` 用 `RB_POWER_OFF`
   - 实机用户确认「能正常命令重启」
4. 熄屏/USB 初步修复：
   - `KmsSurface::present()` 不再从 `Power::Off` 用 `ALLOW_MODESET` 恢复
   - `rest()/turn_off()` 不动 CRTC/LP，避免掉 USB
   - 用户确认：熄屏时 USB 不再掉，但「背光没关」

### 4.5 v3.2（稳定修复阶段 2）

镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-v32-stable-slot-b.img
SHA-256 992131eb4719a36a6d67ec5a494c32c5658a636623719d094d4b66f2232b7e7e
binary I:\rec移植\official-payload\system\bin\recovery-v32
SHA-256 c65cbe9e5c9501240fe7e85e033d08c29e0fbf53e807159f45afb9949e38ac25
```

新增：`ui.rs` 主循环熄屏时强制 `backlight.show(None)`：

```rust
let panel_level = if app.display_on() { panel } else { None };
backlight.show(panel_level)?;
```

结果：USB 保持；但 sysfs 虽 `brightness=0 / actual=0`，用户仍看到明显灰白背光。

### 4.6 v3.3（当前稳定）

镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-v33-stable-slot-b.img
SHA-256 6db790878b5920e8101de7c7abbce7b31735a6522ae16e4d4bd93ffc421a2d73
binary I:\rec移植\official-payload\system\bin\recovery-v33
SHA-256 22ece39049eb71534b6d7411c8a799d587755f54c133f4b5ec0bfa5ebb302c41
```

新增：`Backlight` 支持 `bl_power`：

- `Backlight::show(None)` 写：
  ```text
  brightness = 0
  bl_power = 4   # FB_BLANK_POWERDOWN
  ```
- `Backlight::show(Some(_))` 写：
  ```text
  bl_power = 0
  brightness = level
  ```

这是从 Android 系统熄屏状态反推的：`bl_power=4` 是系统真正熄屏时会写的值。

实机 70 秒 watch 结果：

```text
bl=4 br=0 act=0 panel=0 dpms=On usb=mtp,adb
```

结论：USB 不掉，但屏幕仍有灰白背光；物理关屏未完成。

### 4.7 v3.4（失败，已回滚）

镜像：

```text
I:\rec移植\out\skyward-v0.2.0-TB322FC-v34-stable-slot-b.img
SHA-256 c004e806c7a71ae86a762a1cdf3f0e48663216385f7f1eaf01c4c2378ad954d4
binary I:\rec移植\official-payload\system\bin\recovery-v34
SHA-256 fed50f044396501ee6f1688ebb37addaa798936e3f9dd613d8dac76ca73342c7
```

方案：只改 connector `DPMS=Off/On`，不改 CRTC、不 `ALLOW_MODESET`：

- `rest()/turn_off()` atomic commit 设置 connector DPMS `Off`
- `present()` 唤醒时同一次普通 flip 设置 DPMS `On`
- 保留 `bl_power=4`

结果用户反馈：

```text
背光关掉，usb也掉，然后自动亮屏
```

说明：DPMS Off 确实物理关屏，但这台设备的 DSI/USB 电源域关联导致 USB gadget 掉线并触发恢复。已立即回滚 v3.3。

### 4.8 v4 / v5（失败，严禁继续沿用）

#### v4 binary

```text
I:\rec移植\official-payload\system\bin\recovery-v4
SHA-256 a8c83310143954ef47dcec7abbce7b31735a6522ae16e4d4bd93ffc421a2d73
```

主要改动：`skyward-binder::parcel.rs` header 从 `RECO` 改 `SYST`，解决：

```text
Parcel: Expecting header 0x53595354 but found 0x5245434f. Mixing copies of libbinder?
```

用于 data 解密探索，binder 查询能返回 `described but not registered`，但仍未启动完整 KeyMint 服务链。

#### v5 binary / image

```text
binary I:\rec移植\official-payload\system\bin\recovery-v5
SHA-256 3172523cd8a57c8686e5a75eca71629ca6b6ff8258fb2a343da1b8556492bd7c
image  I:\rec移植\out\skyward-v0.2.0-TB322FC-v5-twrpbase-slot-b.img
SHA-256 774852d768f847dd403e66929660dfb8b1461a783d105eb029b02fc94adf08eb
```

v5 包含中文名、haptics `resonance_hz`、WLAN、SPU/KeyMint/Gatekeeper/Weaver/BootControl 服务链、`SYST` header 等。  
实机日志暴露：

- `/vendor/manifest.xml` 缺失，`servicemanager` 反复报 `NULL VINTF MANIFEST!: device`
- `hlosminkdaemon` 被当常驻服务无限重启
- Gatekeeper/Health/SecureElement 因 VINTF 缺失 `signal 6`
- `ready_service` 等待造成 UI 启动延迟约 20–27 秒
- WLAN 模块跨目录依赖解析失败
- 用户反馈反复黑屏、掉 USB、CPU UI 8.64GHz

结论：**这些实验配置和源码改动不要直接合并到稳定分支**。

---

## 5. 关键诊断证据

### 5.1 v2 背光属性失败日志

```text
I:\rec移植\v2-failure.txt
```

关键行：

```text
recovery failed: panel qcom,mdss_dsi_elden_nt36523_csot_3k_dsc_vid gives its normal maximum as none of [("mi,normal-max-brightness-clone", "mi,max-brightness-clone"), ("mi,max-brightness-normal", "qcom,mdss-dsi-bl-max-level"), ("mi,mdss-dsi-fac-bl-max-level", "qcom,mdss-dsi-bl-max-level")]
```

### 5.2 v3 成功运行日志

```text
I:\rec移植\v3-runtime-verify.txt
```

要点：

```text
/system/bin/recovery ae35a1a605...
recovery PID exists
backlight 410/4095
DSI 1904x3040x120vid
MTP session opened
```

### 5.3 v5 失败日志

```text
I:\rec移植\v5-runtime-verify.txt
I:\rec移植\v3-crypto-state.txt
I:\rec移植\fix-vendor-manifest.txt
I:\rec移植\cli-v4-crypto-probe.txt
```

要点：

```text
3 of the phone's own service descriptions published
/vendor/bin/hlosminkdaemon: pid ... ended: exit status: 0   # 反复
devices not brought up: ... registered no IKeyMintDevice/default
servicemanager: NULL VINTF MANIFEST!: device
Cannot read /vendor/manifest.xml: No such file or directory
Parcel: Expecting header 0x53595354 but found 0x5245434f. Mixing copies of libbinder?
```

### 5.4 CPU 8.64GHz 证据

用户截图显示：

```text
设备型号 联想拯救者Y700（第四代）
处理器 骁龙®8至尊版移动平台
八核 最高 8.64GHz
```

设备实测：

```text
I:\rec移植\cpu-topology.txt
I:\rec移植\probe-v5-info.txt
I:\rec移植\probe-v3-cpu.txt
```

```text
policy0 3532800 kHz
policy6 4320000 kHz
skyward info: cpu = 8 cores, max Some(4320000) kHz
```

结论：sysfs/CLI 是对的；UI 曾错误显示 8.64GHz。v3.1 以后通过 `[cpu] max_khz=4320000` 覆盖显示值；当前稳定配置里已有此项。

### 5.5 系统熄屏状态

文件：

```text
I:\rec移植\screen-on.txt           # 实际采集时系统已处于 OFF/Doze 状态
I:\rec移植\probe-real-backlight.txt
I:\rec移植\test-system-backlight-controls.txt
```

正常 Android 系统熄屏时：

```text
mScreenState=OFF
mActualState=OFF
bl_power = 4
brightness = 0
actual_brightness = 0
panel_power_state = 5
dpms = Off
enabled = enabled
mWakefulness = Dozing
```

`panel_power_state` 尝试 root 写入全部 `Permission denied`，说明它由 HWC/vendor display HAL 控制，不是普通 sysfs 开关。

### 5.6 v3.3 熄屏状态

文件：

```text
I:\rec移植\watch-screen-off.txt
```

连续 70 秒：

```text
bl=4 br=0 act=0 panel=0 dpms=On usb=mtp,adb
```

即：Skyward 已写 backlight powerdown，USB 稳定，但 `panel_power_state`/DPMS 没动，屏幕仍有灰白背光。

### 5.7 v3.4 DPMS-only 结果

用户反馈：

```text
背光关掉，usb也掉，然后自动亮屏
```

已回滚到 v3.3。

---

## 6. 为什么系统能物理熄屏且不掉 USB

系统熄屏走完整 Android 显示/电源栈：

1. `PowerManagerService / DisplayPowerController` 决定 `mScreenState=OFF`
2. SurfaceFlinger / HWC 协调 Display HAL、DSI panel、backlight、firmware
3. Qualcomm HWC / `vendor.qti.hardware.display.*` 调用内核 SDE/DSI panel power 流程，使 `panel_power_state=5`、DPMS Off、背光断电
4. USB gadget 由 Android framework/init 的 `sys.usb.config` 状态机管理，与 display power domain 解耦
5. vendor display HAL 知道哪些 clock/power domain/regulator/DSI PHY 要关，哪些必须保留

Skyward recovery 只有裸 KMS：

- 没有 SurfaceFlinger / HWC / DisplayPowerController
- 直接 `/dev/dri/card0` atomic KMS
- 直接改 connector DPMS 或 CRTC ACTIVE
- USB/MTP 由轻量 `skyward-mtp` 与 TWRP init 维持

所以：

- 裸 KMS `DPMS=Off` → 屏真灭，但 USB 掉
- CRTC `ACTIVE=false + ALLOW_MODESET` → 更严重，黑屏/掉 USB
- 只写 backlight/bl_power → USB 稳，但屏不真灭

**根因是缺少 vendor HWC/display HAL 的 panel-power 调用序列，而不是 `Backlight::show()` 写错。**

---

## 7. 当前稳定 v3.3 配置

文件：

```text
I:\rec移植\devices\TB322FC-stable.toml
SHA-256 3552419ef58f4296300fd86e6fabd9b5ebf81499ffa94c482e89d6fc3cd63b7d
```

内容要点：

```toml
[device]
codename = "TB322FC"
brand = "Lenovo"
model = "联想拯救者Y700（第四代）"
ab = true
os_version_prop = "ro.build.display.id"

[display]
width = 1904
height = 3040
density = 440
diagonal = 8.8
corner_radius = 55

[cpu]
max_khz = 4320000

[modules]
sources = ["vendor_boot", "vendor_dlkm", "vendor", "system_dlkm"]
load = []

[backup]
efs = ["modemst1", "modemst2", "fsg", "fsc", "persist"]
```

刻意**不含**：

```text
[[service]]
[wlan]
[haptics]
[firmware]
[logd]
[owners]
[update]
[stock]
```

原因：这些是 v4/v5 不稳定来源。

---

## 8. 当前稳定源码改动清单（逻辑上属于 v3.3）

注意：工作区源码当前还包含 v3.4 DPMS 改动；以下列出 v3.3 应保留的逻辑。

### 8.1 `crates/skyward/src/ui.rs`

- `NORMAL_MAX` 增加 Lenovo/Qualcomm 回退：
  ```rust
  ("qcom,mdss-brightness-max-level", "qcom,mdss-dsi-bl-max-level")
  ```
- `Backlight` 新增 `power: Option<PathBuf>` 和 `powered_down: bool`
- `Backlight::show(None)` 写 `bl_power=4` + `brightness=0`
- `Backlight::show(Some(_))` 写 `bl_power=0` + brightness
- UI 主循环：
  ```rust
  let panel_level = if app.display_on() { panel } else { None };
  backlight.show(panel_level)?;
  ```

### 8.2 `crates/skyward-ui/src/surface.rs`

v3.3 稳定逻辑应是：

- `present()` 永远普通 page flip；不 `ALLOW_MODESET`，不改 CRTC ACTIVE
- `rest()/turn_off()` 只改变内部 `Power::Resting/Off`，**不做 DRM atomic commit**
- v3.4 加了 DPMS commit，失败；应从 v3.3 基线移除/回退这部分

### 8.3 `crates/skyward-sys/src/lib.rs`

- `power()` 在 `sys.powerctl` 失败后：
  - `sync()`
  - recovery/fastboot 写对应 BCB
  - system 清 BCB
  - raw Linux `reboot(2)` syscall
- 使用常量：
  ```rust
  SYS_REBOOT_AARCH64 = 142
  LINUX_REBOOT_MAGIC1 = 0xfee1_dead
  LINUX_REBOOT_MAGIC2A = 672_274_793
  LINUX_REBOOT_CMD_RESTART = 0x0123_4567
  LINUX_REBOOT_CMD_POWER_OFF = 0x4321_fedc
  ```

### 8.4 `crates/skyward-config/src/lib.rs` + `skyward-info/src/lib.rs`

- 新增 `CpuConfig { max_khz: Option<u32> }`
- `DeviceConfig` 新增 `#[serde(default)] pub cpu: CpuConfig`
- `collect()` 用 `cfg.cpu.max_khz` 覆盖 `Cpu.max_khz`

### 8.5 `crates/skyward-binder/src/parcel.rs`

v3.3 **不应包含** v4 的 `RECO -> SYST` 修改；稳定 v3.3 是 v3 背光修复链，未做 data binder 修复。  
如果接手 data 解密，可以单独把 `SYST` 作为独立分支引入，但不要把它和 WLAN/haptics/服务链一起叠加。

### 8.6 `crates/skyward-config/src/lib.rs` haptics 等

工作区里还有 `resonance_hz` 支持，这是 v5 实验，不在稳定 v3.3 配置里。可作为后续分支保留，但不要直接合入稳定配置。

---

## 9. 设备刷写与验证流程

### 9.1 从 Android 系统写 `recovery_b`

设备有 root：

```bat
adb push <image> /data/local/tmp/skyward.img
adb shell sha256sum /data/local/tmp/skyward.img
adb shell su -c "dd if=/data/local/tmp/skyward.img of=/dev/block/by-name/recovery_b bs=4M status=none; sync; sha256sum /dev/block/by-name/recovery_b"
adb reboot recovery
```

### 9.2 从 recovery 写 `recovery_b`

```bat
adb push <image> /data/local/tmp/skyward.img
adb shell dd if=/data/local/tmp/skyward.img of=/dev/block/by-name/recovery_b bs=4M status=none
adb shell sync
adb shell sha256sum /dev/block/by-name/recovery_b
```

注意：软件重启曾多次被 TWRP init 拒绝；v3.1 后 Skyward 的 `reboot recovery/system` 已修好，但最可靠仍是：

```bat
adb reboot recovery
```

若已在 fastboot：

```bat
fastboot reboot recovery
```

若仍加载旧 rootfs，检查：

```bat
adb shell sha256sum /system/bin/recovery
adb shell sha256sum /dev/block/by-name/recovery_b
```

两者应分别等于当前 binary 和镜像哈希。

### 9.3 回滚到 v3.3

```bat
adb push I:\rec移植\out\skyward-v0.2.0-TB322FC-v33-stable-slot-b.img /data/local/tmp/skyward-v33-stable.img
adb shell dd if=/data/local/tmp/skyward-v33-stable.img of=/dev/block/by-name/recovery_b bs=4M status=none
adb shell sync
adb shell sha256sum /dev/block/by-name/recovery_b
```

应得到：

```text
6db790878b5920e8101de7c7abbce7b31735a6522ae16e4d4bd93ffc421a2d73
```

### 9.4 回到设备最初状态

```bat
I:\rec移植\restore-recovery-TB322FC.bat
```

或：

```bat
fastboot flash recovery_a I:\rec移植\device-backup\recovery_a.img
fastboot flash recovery_b I:\rec移植\device-backup\recovery_b.img
fastboot reboot
```

---

## 10. 未完成问题与建议路线

### 10.1 物理熄屏 + USB 不掉（最高优先级）

当前结论：

- 只写 `brightness=0 + bl_power=4`：USB 稳，屏灰白
- 裸 KMS `DPMS=Off`：背光关，USB 掉
- 系统：`panel_power_state=5 + DPMS Off + bl_power=4`，USB 稳

下一步应：

1. 逆向 vendor display HAL / HWC：
   - 查找 `vendor.qti.hardware.display.composer` / `vendor.qti.hardware.display.*`
   - 查找 `sde-conn-2-DSI-1/panel_power_state=5` 的内核入口
   - 用 `strings`, `nm`, `readelf`, `objdump` 查 `/vendor/lib64/hw/hwcomposer.*.so`, `libsdedrm`, `libqdutils`, `libdisplayconfig` 等
2. 找出「关 panel power 但保留 USB」的 ioctl / DRM property / sysfs 序列
3. 在 Skyward 里用 vendor ioctl 或 HWC display power call 复刻，而不是通用 DPMS/CRTC
4. 每次只改这一项，验证 60 秒不黑屏、不掉 USB

不要再用：

```text
CRTC ACTIVE=false + ALLOW_MODESET
connector DPMS=Off via generic atomic commit
```

这两条都已验证会掉 USB。

### 10.2 data 解密

已知条件：

- v4 `SYST` binder header 修复有效，binder 查询不再 `BR_DEAD_REPLY`
- 但缺 `/vendor/manifest.xml`，`servicemanager` 报 `NULL VINTF MANIFEST!: device`
- 需要启动 SPU KeyMint/Gatekeeper/Weaver，并发布正确 VINTF/SELinux
- 当前 SPU/服务链 v5 会造成黑屏/掉 USB，不能直接叠加

建议顺序：

1. 从 v3.3 基线开分支
2. 只加 `/vendor/manifest.xml` 合成/发布，确认 60 秒稳定
3. 只改 binder header `SYST`，用 `service` CLI 验证
4. 只启动 `keymint-service-spu-qti` 或 `keymint-service-qti`，看 `strongbox/default` 注册
5. 最后再补 Gatekeeper/Weaver/qseecomd/owner/VINTF 权限
6. 每步都验证 UI/USB 稳定，再进下一步

相关证据：

```text
I:\rec移植\crypto-services.txt
I:\rec移植\keymint-manifests.txt
I:\rec移植\cli-v4-crypto-probe.txt
I:\rec移植\v3-crypto-state.txt
I:\rec移植\out\vendor-manifest.xml   # 手工合成过，未固化进稳定镜像
```

关键服务/manifest：

```text
/vendor/etc/vintf/manifest/android.hardware.security.keymint-service-qti.xml
/vendor/etc/vintf/manifest_sun.xml
/vendor/bin/hw/android.hardware.security.keymint-service-spu-qti
/vendor/bin/hw/android.hardware.weaver-service-spu-qti
/vendor/bin/qseecomd
/vendor/bin/hw/android.hardware.boot-service.qti
```

### 10.3 WLAN

事实：

```text
qca_cld3_peach_v2.ko
cnss2.ko
rfkill.ko
wlan0
wpa_supplicant service android.hardware.wifi.supplicant.ISupplicant/default
firmware links under /vendor/firmware/wlan/qca_cld/peach_v2
WCNSS_qcom_cfg.ini -> /vendor/etc/wifi/peach_v2/WCNSS_qcom_cfg.ini
wlan_mac.bin -> /mnt/vendor/persist/peach_v2/wlan_mac.bin
```

v5 失败原因：

- Skyward `modules::load()` 只在请求模块的第一个目录的 `modules.dep` 中找依赖
- 这台设备 `rfkill.ko` 在 `/system_dlkm/lib/modules`，`cfg80211/qca...` 在 `/vendor/lib/modules`
- 导致 `cfg80211: Unknown symbol rfkill_*`
- `/sys/kernel/icnss` 在 recovery 中不存在，不能按小米 `[wlan].writes` 直接写

工作区 `crates/skyward-modules/src/lib.rs` 已有实验性跨目录依赖解析修复和 `system_dlkm` 直接目录回退，但这属于 v5 实验，未在稳定镜像验证。建议单独分支验证。

相关证据：

```text
I:\rec移植\wlan-facts.txt
I:\rec移植\wlan-deps.txt
I:\rec移植\probe-v5-features.txt
```

### 10.4 haptics / 振动

设备：

- 两个 `aw-haptic-hv` FF 输入设备
- `FF_RUMBLE`, `FF_PERIODIC`, `FF_CONSTANT`, `FF_CUSTOM`, `FF_GAIN`
- 无 `resonance` sysfs 文件
- 源码已有 `resonance_hz` 支持（v5 实验）
- 稳定 v3.3 不含 `[haptics]`

建议：用 `skyward haptic --help` 和 FF 设备单独测试；不要和 data/WLAN/服务链一起叠加。

### 10.5 CPU / 名称 / 重启

这三个已在 v3.3 稳定：

- 中文名：`联想拯救者Y700（第四代）`
- CPU：配置 `[cpu] max_khz=4320000`，UI 显示 4.32GHz
- 命令重启：BCB + raw `reboot(2)` fallback

不要再改真实 CPU 调度或频率。

---

## 11. 验证清单（每次刷镜像后必须执行）

```bat
adb devices
adb shell sha256sum /system/bin/recovery
adb shell sha256sum /skyward/device.toml
adb shell sha256sum /dev/block/by-name/recovery_b
adb shell getprop sys.usb.state
adb shell pidof recovery
```

熄屏监控：

```bat
adb push I:\rec移植\watch-screen-off.sh /data/local/tmp/watch-screen-off.sh
adb shell chmod 755 /data/local/tmp/watch-screen-off.sh
adb shell nohup /data/local/tmp/watch-screen-off.sh >/data/local/tmp/watch-screen-off.stdout 2>&1 &
```

然后等自动熄屏，读取：

```bat
adb shell cat /data/local/tmp/watch-screen-off.txt
```

重点字段：

```text
bl_power
brightness
actual_brightness
panel_power_state
dpms
sys.usb.state
```

命令重启：

```bat
adb push <binary> /data/local/tmp/skyward-binary
adb shell chmod 755 /data/local/tmp/skyward-binary
adb shell /data/local/tmp/skyward-binary reboot recovery
```

验证 CPU / 名称：

```bat
adb shell /data/local/tmp/skyward-binary info --config /skyward/device.toml
```

应含：

```text
model = 联想拯救者Y700（第四代）
cpu = 8 cores, max Some(4320000) kHz
```

---

## 12. 文件索引

### 稳定交付

```text
README-TB322FC-STABLE.md
HANDOFF-TB322FC-Skyward.md
devices/TB322FC-stable.toml
out/skyward-v0.2.0-TB322FC-v33-stable-slot-b.img
official-payload/system/bin/recovery-v33
restore-recovery-TB322FC.bat
device-backup/SHA256SUMS.txt
```

### 构建/打包

```text
skyward-pack-linux
port_tool.py
make-v3.sh
make-v31.sh
make-v32.sh
make-v33.sh
make-v34.sh
make-v5.sh
wsl-build-v31-binary.sh
wsl-build-v32-binary.sh
wsl-build-v33-binary.sh
wsl-build-v34-binary.sh
wsl-build-v4-binary.sh
wsl-build-v5-binary.sh
```

### 诊断证据

```text
v2-failure.txt
v3-runtime-verify.txt
v5-runtime-verify.txt
probe-v3-cpu.txt
cpu-topology.txt
screen-on.txt
probe-real-backlight.txt
test-system-backlight-controls.txt
watch-screen-off.txt
test-bl-power.txt
probe-dsi-properties.txt
wlan-facts.txt
wlan-deps.txt
crypto-services.txt
keymint-manifests.txt
cli-v4-crypto-probe.txt
```

### 脚本/工具

```text
collect-recovery-diag.sh
collect-v2-diag.sh
verify-v5-runtime.sh
verify-v31-runtime.sh
verify-v33-screen-off.sh
watch-screen-off.sh
probe-system-screen.sh
probe-real-backlight.sh
test-system-backlight-controls.sh
```

---

## 13. 给接手 agent 的硬约束

1. **从 v3.7 基线开始**：镜像 `36c0b121…` / binary `fb211bf4…` / config `3552419e…`。
2. 每次只改一个功能；不要同时动 data、WLAN、haptics、熄屏。
3. 每次只刷 `recovery_b`，设备内 `dd` 后必须回读分区哈希。
4. 每次重启后先确认：
   - 60 秒不黑屏
   - USB/adb 不掉
   - `recovery` PID 稳定
   - 日志无 `recovery failed` / HAL restart loop
5. 失败立即回滚到 v3.7：
   ```text
   36c0b121827add264c506b62bfc11b3e6c3d418c991be2238aeb7db2edbea96a
   ```
   （v3.3 也可作为更保守的回退：`6db790878b5920e8101de7c7abbce7b31735a6522ae16e4d4bd93ffc421a2d73`）
6. 不要再用以下组合：
   - `recovery_a.img` Android15 ramdisk 给 Android16 B 槽打包
   - `CRTC ACTIVE=false + ALLOW_MODESET`
   - generic connector `DPMS=Off`
   - v5 的完整服务链/WLAN/haptics 配置
7. 熄屏与 USB 已在 v3.7 解决（见第 15 节），不要回退到 DPMS/CRTC 方案。

---

## 14. 最终状态

设备当前运行稳定 v3.7 recovery，adb/MTP 正常，熄屏背光全黑且不掉 USB。  
可以安全交接给其他 agent 继续做 data / WLAN / 振动。

---

## 15. v3.7：熄屏与 USB 的根因与修复（2026-11-08 晚）

这一节记录 v3.3 → v3.7 的完整定位过程。**两个问题彼此独立**，之前一直混在一起。

### 15.1 硬件与驱动链路（实测）

```text
/sys/class/backlight/panel0-backlight
  → msm_drm 的 sde_backlight_device_update_status
  → msm_drm_notifier MSM_DRM_EVENT_BL_UPDATE
  → 内建的 aw99706a I2C 背光驱动（i2c-5, 地址 0x76）
```

关键事实：

- 面板 DT 只有 `qcom,mdss-dsi-bl-pmic-control-type = "bl_ctrl_external"`，**没有背光 GPIO**。
- I2C 上：`5-0076` 绑定驱动 `i2c-bl`（真正的背光 IC），`5-0011` 未绑定，`5-003e` 是 `bias`。
- `i2c-bl` 驱动内建在 `msm_drm.ko` 里（`module -> msm_drm`），没有暴露任何 sysfs 寄存器接口。
- `CONFIG_I2C_CHARDEV is not set`，**没有 `/dev/i2c-N`**，用户态无法直接写 IC。
- 没有背光字符设备（`/proc/devices` 里没有 sde/backlight 主设备号）。

从 `msm_drm.ko` 的符号表解析出的寄存器表（每项 3 字节：reg, val, mask）：

```text
aw99706a_init_table (8 项):
  0d=00, 0c=48, 06=d9, 07=05, 04=00, 05=00, 08=01, 0d=f8
aw99706a_suspend_table (1 项):
  0d=00                      ← 真正的关断
```

`reg 0x04/0x05` 是 16 位亮度，`reg 0x0d=0xf8` 是使能、`0x00` 是关断。
实机 `BL_REGS` 回读与 init 表完全吻合（`0c=48, 0d=f8, 06=d9, 07=05, 08=01`）。

### 15.2 为什么背光关不掉

用「写值后看 dmesg 是否出现 `_bl_set_brightness`」和「`BL_REGS` 寄存器回读」做了定量验证：

| 写入 | 驱动是否收到 | IC 寄存器 |
|---|---|---|
| `brightness=4095` | 是 | `04/05 = 0x0fff` |
| `brightness=100` | 是 | `04/05 = 0x0064` |
| `brightness=2` | 是 | `04/05 = 0x0002` |
| `brightness=1` | 是 | `04/05 = 0x0001` |
| `brightness=0` | **否，完全没有内核日志** | 保持上一次的值 |
| `bl_power=4` | **否** | 保持上一次的值 |

结论：`sde_backlight_device_update_status` 把亮度 0 整个丢弃（防闪烁），
`bl_power` 的非 0 值也只是让该函数提前返回。

后果：UI 熄屏前先做渐暗动画，最后一帧是 5% 亮度（205/4095）；
之后写 `brightness=0` 被丢弃，IC 保持 205 → 屏幕呈"灰白背光"。

更糟的是 **`bl_power != 0` 会阻塞所有后续亮度写入**：

```text
blp=4 然后 brightness=4095  → 驱动无任何动作（delta=0）
blp=0 然后 brightness=4095  → 正常生效（delta=1）
```

所以 v3.3 的写法（先 `bl_power=4`，再 `brightness=0`）是双重错误：
既没关断 IC，又把后续写入通道堵死了。

**修复（v3.7）**：

```rust
// 熄屏用 IC 接受的最小值，而不是 0
let raw = level.map_or(1, |v| ((v.clamp(0.0, 1.0) * self.top as f32).round() as u32).max(1));
```

并且：

- 永不写 `bl_power=4`；
- `Backlight::open()` 时若发现 `bl_power != 0`，先写 0，保证亮度通道可用。

`1/4095 ≈ 0.02%`，实测视觉上等于全黑（用户确认"基本全黑，可以接受"）。

### 15.3 为什么熄屏会掉 USB

**不是硬件电源域耦合，是 recovery 进程崩溃被 init 重启。**

v3.5 的日志给出了直接证据：

```text
[   98.603219] recovery failed: turn DPMS off: Invalid argument (os error 22)
[   98.691611] TB322FC 0.2.0 recovery up, misc command "" args [], asking for Menu
```

过程：

1. 熄屏时 `KmsSurface::rest()` 尝试用 atomic commit 把 connector `DPMS` 设为 `Off`；
2. 只改 connector 属性的 commit 会让 DRM 认为 `connectors_changed`，没有
   `ALLOW_MODESET` 就返回 `EINVAL`；
3. `rest()?` 把错误抛到 `ui::run`，recovery 进程退出；
4. init 重启 recovery → 重新初始化 USB gadget（主机看到断连）+ 重新点亮屏幕。

这解释了两个现象：**USB 掉线** 和 **自动亮屏** 同时发生。

v3.6 把 `rest()/turn_off()/present()` 的失败改为非致命（只记日志），
结果进程不再重启（`pid` 不变、`recovery up` 计数不变），USB 全程稳定 —— 机制确认。

**修复（v3.7）**：既然 `brightness=1` 已经能让屏幕全黑，就**完全不碰 DRM**：

```rust
pub fn rest(&mut self) -> Result<()> {
    if self.power == Power::On { self.power = Power::Resting; }
    Ok(())
}
pub fn turn_off(&mut self) -> Result<()> {
    self.power = Power::Off;
    Ok(())
}
```

`present()` 也回到纯 page flip，不再改 DPMS / CRTC / LP。
没有可失败的 DRM 调用，也就没有崩溃重启的可能。

### 15.4 实机验证（v3.7）

熄屏 60 秒连续采样：

```text
t=0s  br=1 pid=506 usb=mtp,adb dpms=On
t=2s  br=1 pid=506 usb=mtp,adb dpms=On
...
t=58s br=1 pid=506 usb=mtp,adb dpms=On
```

- 亮度稳定在 1，视觉全黑；
- `usb=mtp,adb` 全程不变；
- `pid` 不变，`grep -c 'recovery up'` = 1（从未重启）；
- 电源键唤醒正常，亮度恢复（用户实测确认）。

熄屏时的渐变实测：`287 → 178 → 123 → 1`，然后稳定。

### 15.5 失败方案存档（不要重试）

| 方案 | 结果 |
|---|---|
| `bl_power=4` + `brightness=0`（v3.3） | 背光不灭，且阻塞后续写入 |
| connector-only `DPMS=Off`（v3.4/v3.5） | EINVAL → 进程重启 → 掉 USB + 自动亮屏 |
| `DPMS=Off` + `ALLOW_MODESET`（v3.6） | 仍 EINVAL，UI 每轮重试最终把设备弄挂 |
| `unbind`/`bind` i2c-bl 驱动 | unbind 成功但 bind 报 `probe failed with error -5`，驱动无法恢复 |
| 用户态直接写 I2C 寄存器 | `CONFIG_I2C_CHARDEV` 未开启，无 `/dev/i2c-N` |

### 15.6 给后续 agent 的提示

- 如果将来要做**真正的硬件断电**（而不是亮度=1），唯一已知路径是 `bl_suspend`
  写入 `aw99706a_suspend_table`（`reg 0x0d=0x00`），而它只在 panel power-off 时被调用。
  要么让 vendor HWC 来做，要么改内核模块，两者都超出当前范围。
- 亮度=1 在暗室仔细看可能有极微弱漏光，这是 LCD 面板本身的特性；
  当前方案在正常使用环境下视觉全黑。
- 继续做 data/WLAN/振动时，**不要**再引入 DPMS/CRTC 改动；
  熄屏路径保持"只改亮度"。

---

## 16. v3.8–v3.12：SD 卡与 data 解密（2026-11-09）

当前稳定版本是 **v3.12**：

```text
镜像   out/skyward-v0.2.0-TB322FC-v312-stable-slot-b.img
       3fca684f2bfa559f2fd5df709eb67b8416e60ff7ac224e8fc0c507d6c6894665
binary official-payload/system/bin/recovery-v312
       1207e75f5d83aae74e8460802e7fa31d127a7c0a343ea7e0ff31af39f60d4484
config devices/TB322FC-stable.toml
       aab764f0556a68c9be186ea223b17bcf8e8949b3871fe3150bfc0232ee8dbad1
```

实机已验证：data 解密成功并挂载、外置 SD 卡挂在 `/external_sd`、
熄屏全黑、USB 稳定、CPU/中文名/命令重启正常。

### 16.1 SD 卡

原 ramdisk 的 `recovery.fstab` 与 init **都没有 SD 卡条目**；Skyward 的
`/sdcard` 是解密后的 `/data/media`，本身没有外置卡概念。

新增 `crates/skyward/src/sd.rs` 与 `[sd]` 配置：

```toml
[sd]
mount = "/external_sd"
wait_seconds = 8
```

实现要点：

- 扫描 `/sys/class/block` 的 `mmcblk*`，排除 `boot0`/`boot1`/`rpmb`；
- 分区（有 `partition` 文件）优先，整盘其次；
- 按 `vfat → exfat → ext4 → f2fs` 先读写、再只读尝试；
- 失败只写 kmsg，不影响启动；
- 在 `bring_up` 里、`[partitions] mounted` 之后调用。

实测：`mmcblk1p1`（SL16G 14.8GiB，vfat）挂载成功。

**注意**：SD 卡挂载代码在 `bring_up` 里，而 `prepare()` 在
`mount_partitions` 失败时会**跳过整个 `bring_up`**。调试时若发现 SD
没挂载、模块没加载、服务没起，先看 `dmesg | grep "partitions not mounted"`。

### 16.2 data 解密：四个必要条件

**(1) VINTF 必须写在 framework manifest**

servicemanager 读 `/system/etc/vintf/manifest.xml` 与 `/vendor/manifest.xml`。
这台设备没有 `/vendor/manifest.xml`：

```text
servicemanager: Cannot read /vendor/manifest.xml: No such file or directory
servicemanager: NULL VINTF MANIFEST!: device
```

所以所有 HAL 都要写进 `/system/etc/vintf/manifest.xml`。v3.9 起由
`make-v39.sh` 从 vendor 自带描述生成（11 个 HAL，剔除本机不存在的
strongbox/oplus/secure_element 条目，避免 lazy-start 刷屏）。

**(2) KeyMint 卡在 `WaitForPropertyCreation`**

`libqtikeymint.so` 启动时等：

```cpp
WaitForPropertyCreation("vendor.gatekeeper.is_security_level_spu")
```

该属性在 recovery 中从未被设置 → KeyMint 永不 addService →
`IKeyMintDevice/default is not running`。

诊断技巧：读 `/proc/<pid>/task/<tid>/syscall` 拿 futex 地址，再看它落在
哪个 `/proc/<pid>/maps` 区间；落在
`/dev/__properties__/properties_serial` 就是在等属性。

修复：init 里启动 keymint 之前 `setprop vendor.gatekeeper.is_security_level_spu 0`。

**(3) SPU 模块路径**

原 init：`insmod /vendor/etc/spu_modules/*.ko` —— 该目录不存在。
真实路径是 `/vendor/lib/modules/spss_utils.ko`、`spcom.ko`。
加载后才会出现 `/dev/spcom`，SPU 才能工作。

**(4) SPU 守护进程必须 root**

`sec_nvm`、`spdaemon`、`weaver-service-spu-qti` 以 `system` 运行会
**立刻 exit 127**；root 运行正常并注册 `IWeaver/default`。
v3.9 起在 ramdisk init 里定义 `skyward_sec_nvm` / `skyward_spdaemon` /
`skyward_weaver` 三个 root 服务。

### 16.3 fstab 来源

Skyward 的 `skyward_block::fstab::FILES` 原本只读
`/vendor/etc/fstab.qcom` 和 `/odm/etc/fstab.qcom`，而 recovery 里
**这两个文件都不存在**（Android 16 把 fstab 放在 vendor_boot ramdisk）。
于是报 `the phone's own table says nothing about /data`。

v3.10 起 `FILES` 追加 `/system/etc/recovery.fstab` 和 `/etc/recovery.fstab`
（TWRP 的表，含完整的 `fileencryption` / `metadata_encryption` /
`keydirectory` 参数）。

### 16.4 /metadata 的竞争

`skyward_vab::mount_partitions` 第一步就挂 `/metadata`。v3.9/v3.10 让 init
也挂了一次，两者竞争：init 抢先则 Skyward 得到 EBUSY → `prepare()` 记
`partitions not mounted: ...` 并**跳过 `bring_up`**（SD、模块、服务全跳过）。

v3.12：移除 init 的 `/metadata` 挂载，并让 `mount_partitions` 在
`mount_ro` 失败后重新检查 `is_mount_point`，只有仍未挂载才报错。

### 16.5 USB 保活

`keep_the_cable()`（`skyward/src/main.rs`）在 `recovery()` 开头起一个线程，
每 2 秒扫描 `/sys/bus/platform/devices/*.dwc3`，把 `power/control` 写成
`on`，并持有 `/sys/power/wake_lock` 里的 `skyward-recovery`。

必须循环写：控制器在 recovery 启动后才注册，而且切换 USB 功能会把
`control` 重置回 `auto`。

### 16.6 用户可见路径

- 文件管理在 **高级** 页（不是主界面）。
- SD 卡：文件管理 → `/` → `external_sd`。
- data 解密入口在 data 页，成功后 `/sdcard` 可见。

### 16.7 版本链

```text
v3.8  e3fa5e5a  SD 卡支持 + init crypto 触发修复
v3.9  6c7090f3  framework manifest / is_security_level_spu / SPU 路径 / root 守护进程
v3.10 48884251  recovery.fstab 回退  → 解密首次成功
v3.11 f915a527  USB 保活（keep_the_cable）
v3.12 3fca684f  修 /metadata 竞争，SD 恢复，全功能验证通过
```

### 16.8 尚未完成

- **WLAN**：`qca_cld3_peach_v2` 跨目录模块依赖 + `/sys/kernel/icnss` 缺失。
- **振动**：两个 `aw-haptic-hv` FF 设备，无 `resonance` sysfs。
- 两项都应在 v3.12 基线上逐项加，每次验证 60 秒不黑屏、不掉 USB。

