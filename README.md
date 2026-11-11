# Skyward for Lenovo LEGION Y700 (4th Gen) — TB322FC

把 [Skyward](https://github.com/kirklin/skyward) 移植到联想拯救者 Y700（第四代 / TB322FC）的**完整源码树**，
已包含移植改动，克隆下来即可直接编译。

- **上游版本：Skyward v0.2.0**（commit `22528ba`，`chore: release 0.2.0`）
- 本仓库 = 上游 v0.2.0 源码 + TB322FC 移植改动 + 设备配置 + 构建/打包脚本
- 许可：GPL-3.0（与上游一致）
- `patches/skyward-tb322fc.patch` 是相对上游 v0.2.0 的完整差异，便于对照审查

### 仓库结构

```text
crates/                  上游源码 + 移植改动（crates/skyward/src/sd.rs 为本移植新增）
devices/TB322FC.toml     本机配置（CPU 显示、SD 卡挂载点等）
ramdisk/                 本移植改写的两个 ramdisk 文件
  init.recovery.qcom.rc     crypto 初始化（KeyMint / Gatekeeper / SPU / Weaver）
  system/etc/vintf/manifest.xml  framework VINTF 描述
scripts/
  build-binary.sh        编译 arm64 二进制
  make-image.sh          从自己的 recovery_b 备份生成整分区镜像
  port_tool.py           boot image / cpio / LZ4 / AVB 处理
patches/                 相对上游 v0.2.0 的差异
docs/HANDOFF.md          完整技术记录（内部修订号 v3.x 与上游版本无关）
docs/upstream-README*.md 上游 Skyward 的原 README
```

---

## 设备与系统

| 项目 | 值 |
|---|---|
| 机型 | Lenovo TB322FC（联想拯救者 Y700 第四代） |
| 产品名 | `elden_prc_wifi` |
| 平台 | Qualcomm `sun` / SM8750（骁龙 8 Elite） |
| **系统版本** | `TB322FC_CN_OPEN_USER_Q00041.1_W_ZUXOS_1.5.10.294_ST_260714`（ZUXOS 1.5.10.294） |
| **Android 版本** | **Android 16（SDK 36）** |
| 内核 | `6.6.118-android15-8-g350f378eb496-ab14943902-4k` |
| 安全补丁 | system `2026-05-05`，vendor `2025-02-05` |
| 槽位 | A/B，测试时运行在 `_b` |
| 屏幕 | 1904×3040，8.8"，440 dpi，圆角 55 |
| 面板 | `qcom,mdss_dsi_elden_nt36523_csot_3k_dsc_vid` |
| 背光 IC | Awinic `aw99706a`（I²C-5 `0x76`） |
| 触控 | `NVTCapacitiveTouchScreen` |

> 测试基线是 **`recovery_b` 分区原本的 TWRP 镜像**（`twrp_elden-eng 16.1.0`，Android 16 ramdisk）。
> `recovery_a` 上的联想原厂 Android 15 recovery 不能作为基底。

---

## 可用 / 不可用

### ✅ 已实机验证可用

| 功能 | 说明 |
|---|---|
| 启动、显示、触控 | 1904×3040 正常点亮 |
| adb | 正常 |
| MTP | 正常，可访问 `/sdcard` 与 `/external_sd` |
| 中文设备名 | 显示「联想拯救者Y700（第四代）」 |
| CPU 频率显示 | 显示 4.32 GHz（未改动真实频率/调度） |
| 命令重启 | `system` / `recovery` / `fastboot` / `bootloader` 均可 |
| 熄屏 | 背光真正熄灭（亮度 1/4095，视觉全黑） |
| 熄屏时 USB | 不掉线 |
| **data 解密** | **仅无锁屏密码时测试通过**（见下方警告） |
| **外置 SD 卡** | 自动挂载到 `/external_sd` |

### ⚠️ 未测试

Skyward 自带的分区备份 / 恢复、OTA 包安装、擦除、SELinux 上下文修复等页面可以打开，
但本移植**没有逐项完整验证**。

### ❌ 不可用 / 未实现

| 功能 | 原因 |
|---|---|
| WLAN | `qca_cld3_peach_v2` 模块跨目录依赖，且 recovery 中 `/sys/kernel/icnss` 不存在 |
| 振动 | 两个 `aw-haptic-hv` FF 设备，没有 `resonance` 频率 sysfs |
| **有密码时的 data 解密** | **未测试，预期不可用**（见下） |

---

## ⚠️ data 解密的重要限制

**本移植只在「设备没有锁屏密码 / 图案 / PIN」的情况下测试过 data 解密。**

- 无密码时：`/metadata` 的密钥可由 KeyMint 直接解开，解密成功，`/sdcard` 可见。
- 有密码时：需要 Gatekeeper 校验凭据后再解 CE 密钥。本移植虽然把
  Gatekeeper 起来了，但**没有在有密码的设备上验证过**，请不要假定它可用。
- 解密是**只读意义上的安全操作**（dm-crypt 映射后挂载），但**不要在有重要数据的机器上
  把「解密成功」当作数据安全的保证**，先备份。

---

## 安装

需要：bootloader 已解锁、设备是 TB322FC、`recovery_b` 是本文测试基线或相近的 TWRP。

### 成品镜像

从 [Releases](https://github.com/BeeHiyok/Y700-Gen4_skyward/releases) 下载：

```text
skyward-v0.2.0-TB322FC-recovery.img
大小     104857600 字节（整分区）
SHA-256  4d29e75849f14a5caf14677d4543da9c7997414869d9def109546a8038cf656a
```

> 这个镜像是 `[power] charge = false`（保 adb、不充电）。需要充电时把配置里的
> `charge` 改成 `true` 重新打包，见「充电与 OTG」一节。

```bash
# 校验
sha256sum skyward-v0.2.0-TB322FC-recovery.img

# 写入 recovery_b
adb push skyward-v0.2.0-TB322FC-recovery.img /data/local/tmp/skyward.img
adb shell su -c 'dd if=/data/local/tmp/skyward.img of=/dev/block/by-name/recovery_b bs=4M'
adb shell su -c 'sync'
adb shell su -c 'sha256sum /dev/block/by-name/recovery_b'
adb reboot recovery
```

回滚：

```bash
fastboot flash recovery_b <你自己的 recovery_b 备份.img>
```

**刷之前务必备份 `recovery_a` / `recovery_b` / `boot` / `init_boot` / `vendor_boot` / `dtbo` / `vbmeta`。**

---

## 从源码构建

克隆即可编译，无需再打补丁。

```bash
git clone https://github.com/BeeHiyok/Y700-Gen4_skyward.git
cd Y700-Gen4_skyward

# 依赖：Rust（rustup 安装的 stable）、Android NDK r29、cargo-ndk
# rustup target add aarch64-linux-android  （脚本会自动执行）
export ANDROID_NDK_HOME=/opt/android-ndk-r29

# 1. 编译 arm64 二进制
./scripts/build-binary.sh ./skyward-tb322fc-recovery

# 2. 用自己的 recovery_b 备份作为基底，生成整分区镜像
./scripts/make-image.sh \
    ./recovery_b-stock.img \
    ./skyward-tb322fc-recovery \
    ./skyward-v0.2.0-TB322FC-recovery.img
```

**可复现性**：在干净目录里 `cargo ndk -t arm64-v8a --platform 30 build --locked --release -p skyward`
产出的二进制与 Release 里的完全一致：

```text
SHA-256 1207e75f5d83aae74e8460802e7fa31d127a7c0a343ea7e0ff31af39f60d4484
```

`make-image.sh` 会替换 ramdisk 里的：

| 路径 | 内容 |
|---|---|
| `system/bin/recovery` | 编译出的 Skyward |
| `skyward/device.toml` | `devices/TB322FC.toml` |
| `init.recovery.qcom.rc` | `ramdisk/init.recovery.qcom.rc` |
| `system/etc/vintf/manifest.xml` | `ramdisk/system/etc/vintf/manifest.xml` |

并重新打 AVB hash footer（`algorithm NONE`），输出与分区等长的镜像。

---

## 这个移植做了什么

完整的技术记录见 [`docs/HANDOFF.md`](docs/HANDOFF.md)，这里只列要点。

> `docs/HANDOFF.md` 里的 `v3.x` 是移植过程中的内部修订号，和上游版本号无关；
> 对外发布的版本一律对齐上游 **v0.2.0**。

### 1. 背光与熄屏

`msm_drm` 的 `sde_backlight_device_update_status` 会**丢弃 `brightness=0`**，
并且 `bl_power != 0` 时会**忽略所有亮度写入**。所以：

- 熄屏写 `brightness=1`（IC 接受的最小值，视觉全黑），不写 `bl_power=4`；
- 完全不碰 DRM（改 connector DPMS 会掉 USB）。

### 2. USB

熄屏掉 USB 的根因是 recovery 进程崩溃被 init 重启（USB gadget 重建），
不是硬件耦合。另外 `keep_the_cable()` 每 2 秒把 dwc3 的 `power/control`
写回 `on` 并持有 wakelock，防止长时间熄屏后主机丢设备。

### 3. data 解密（四个必要条件）

1. **VINTF**：这台设备没有 `/vendor/manifest.xml`，HAL 必须声明在
   `/system/etc/vintf/manifest.xml`；
2. **KeyMint 等一个属性**：`libqtikeymint.so` 启动时
   `WaitForPropertyCreation("vendor.gatekeeper.is_security_level_spu")`，
   不设置就永不注册；
3. **SPU 模块路径**：模块在 `/vendor/lib/modules/`，不在 `/vendor/etc/spu_modules/`；
4. **SPU 守护进程要 root**：`sec_nvm` / `spdaemon` / `weaver` 以 `system`
   运行会立刻 exit 127。

另外 Skyward 只读 `/vendor/etc/fstab.qcom`（recovery 里不存在），已追加
`/system/etc/recovery.fstab` 回退。

### 4. SD 卡

recovery 的 fstab 与 init 都没有 SD 卡条目，新增 `sd.rs` 扫描
`/sys/class/block/mmcblk*` 并自动挂载到 `/external_sd`。

---

## 使用提示

- **文件管理不在主界面**：主界面 → **高级** → **文件管理**。
- SD 卡：文件管理里从 `/` 进入 `external_sd`。
- data 解密入口在 data 页。

---

## 充电与 OTG：同一个根因

这台机器的 5V 供电和 Type-C 角色**不由 Linux 控制**：设备树里 `ssusb@a600000` 的
供电是 `dummy-supply`，真正管它的是 PMIC 上的 PD 固件，通过
`pmic_glink → ucsi_qti_glink → qti_battery_charger` 这条链，而这段固件**跑在 ADSP 上**。

recovery 里 ADSP 默认 offline——内核在 **1.08 秒**就尝试启动它，那时 `/firmware`
还没挂载：

```text
[1.088157] remoteproc0: Direct firmware load for adsp.mdt failed with error -2
[1.088163] request_firmware failed: -2
```

后果有两个，都是同一个原因：

| | 充电 | adb |
|---|---|---|
| ADSP 关闭（默认） | ❌ 完全无电流 | ✅ |
| ADSP 启动（`[power] charge = true`） | ✅ 两个口都能充 | ❌ 端口只取电，不枚举 |

`charge = true` 时 Skyward 会先挂 `/firmware`、启动 ADSP、等 `power_supply` 出现，
再把 UDC 重绑并走 `none → adb` 重建 gadget；每一步写进
`/mnt/vendor/persist/skyward-power.log`（重启后仍可读，dmesg 会丢）。

**为什么不能共存**：PD 栈起来后只把端口当成取电（日志里 `usb-online = 0`、
`usb-type = Unknown`，而 Android 里是 `online = 1`、`real_type = PD`）。
Type-C 要传数据，除了 CC 角色还得把数据通道经 mux（`fsa4480` / `ptn3222`）
路由到 SoC，这一步由 PD 栈按协商结果做，而 Android 里是 USB HAL 通知它"要数据"，
recovery 没有这个 HAL。内核侧一切正常（`mode=peripheral`、`role=device`、
UDC 已绑、`sys.usb.state=adb`），**唯独物理数据通路没被打开**。

所以 **U 盘（OTG）在 recovery 里也拿不到 5V**，插上不会枚举。
纯 sysfs 手段无效：`typec/port0/data_role` 是只读状态量，`usb/input_suspend=0`、
重插数据线都不能恢复枚举。

这不是移植引入的回归：TWRP 在这台机器上同样不跑 PD 栈（它的 init 里
`wait /sys/class/power_supply/battery` 同样超时失败），表现一致。

**替代方案**：`adb push` / MTP 传文件、外置 SD 卡 `/external_sd`；
需要充电时用 `charge = true` 的配置，或直接开机进系统充。

## 重启目标

`system` / `recovery` / `bootloader` / `edl` 都验证可用。

`bootloader` 和 `edl` 走内核的 `RESTART2` + 字符串（`"bootloader"` / `"edl"`），
**不经过 `sys.powerctl`**：recovery 的 init 只认 `reboot,` 前缀，会直接做普通重启，
结果就是"点 bootloader 却回到系统"。



- 本仓库的补丁衍生自 [kirklin/skyward](https://github.com/kirklin/skyward)，遵循 **GPL-3.0**。
- Skyward 是独立实现的 recovery，与本移植无关的 bug 请提到上游。
