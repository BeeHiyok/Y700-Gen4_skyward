# Skyward for Lenovo LEGION Y700 (4th Gen) — TB322FC

把 [Skyward](https://github.com/kirklin/skyward) 移植到联想拯救者 Y700（第四代 / TB322FC）的补丁与工具。

- **上游版本：Skyward v0.2.0**（commit `22528ba`，`chore: release 0.2.0`）
- 本仓库只包含**移植所需的补丁、配置、ramdisk 覆盖文件和构建脚本**，不含上游源码
- 许可：GPL-3.0（与上游一致）

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
SHA-256  3fca684f2bfa559f2fd5df709eb67b8416e60ff7ac224e8fc0c507d6c6894665
```

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

```bash
# 1. 取上游 Skyward v0.2.0
git clone --depth 1 --branch v0.2.0 https://github.com/kirklin/skyward.git
export SKYWARD_SRC=$PWD/skyward

# 2. 打补丁并编译 arm64 二进制
#    需要 Rust stable、Android NDK r29、cargo-ndk
#    rustup target add aarch64-linux-android
./scripts/build-binary.sh ./skyward-tb322fc-recovery

# 3. 用自己的 recovery_b 备份作为基底，生成整分区镜像
./scripts/make-image.sh \
    ./recovery_b-stock.img \
    ./skyward-tb322fc-recovery \
    ./skyward-v0.2.0-TB322FC-recovery.img
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

## 许可与致谢

- 本仓库的补丁衍生自 [kirklin/skyward](https://github.com/kirklin/skyward)，遵循 **GPL-3.0**。
- Skyward 是独立实现的 recovery，与本移植无关的 bug 请提到上游。
