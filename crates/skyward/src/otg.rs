//! The port as a host, for a USB stick plugged into it.
//!
//! A phone's port is a device by default, and what turns it into a host is the
//! Type-C controller's software: UCSI, driven by the installed system's
//! firmware and daemons. A recovery runs none of that, so on this phone a stick
//! plugged in is never seen — the controller never switches, and nothing
//! enumerates. The recovery asks the controller directly instead.
//!
//! The port cannot be both: while it is a host, adb and file transfer are
//! gone. So it is given to a stick only when the pages ask, and given back as
//! soon as the stick goes, or when none appeared at all.

use anyhow::{bail, Context, Result};
use std::time::Duration;

/// Where the port is told to be a host, or a device again. The controller
/// underneath is a dwc3; this node is the one its glue driver exposes, and
/// writing it goes through the same role change UCSI would ask for, boost
/// supply and all.
const MODE: &str = "/sys/bus/platform/devices/a600000.ssusb/mode";

/// What the controller says the port is now.
fn mode() -> String {
    std::fs::read_to_string(MODE).map(|m| m.trim().to_string()).unwrap_or_default()
}

/// Whether the port is a host now.
pub fn is_host() -> bool {
    mode() == "host"
}

/// Whether the port can power a stick at all on this phone, now.
///
/// The 5 V a stick needs is not a kernel regulator here: the controller's
/// supply is a dummy, and the boost that feeds the port belongs to the PMIC's
/// charger, which runs on the ADSP. `power::start` brings that up; when it did
/// not, no stick would ever be powered and taking the port would only lose
/// adb.
fn can_power_a_stick() -> bool {
    crate::power::up()
}

/// Give the port to a host controller, so a stick plugged into it enumerates.
pub fn to_host() -> Result<()> {
    if !can_power_a_stick() {
        bail!(
            "这个口要靠充电/PD 固件提供 5V，而 recovery 里那套没有起来，接上 U 盘也不会枚举。用 adb 或 SD 卡传文件。"
        );
    }
    // A gadget still bound holds the controller in device mode, and its adbd
    // holds the port, so it goes first.
    let _ = skyward_sys::usb::set("none", Duration::from_secs(5));
    std::fs::write(MODE, "host").with_context(|| format!("write host to {MODE}"))?;
    std::thread::sleep(Duration::from_millis(400));
    if !is_host() {
        // Put it back the way it was rather than leave the port unusable.
        let _ = to_device();
        bail!("the port did not take host mode");
    }
    skyward_sys::kmsg("the port is a host now: a USB stick plugged in shows under /mnt/usb")?;
    Ok(())
}

/// Give the port back to the computer, so adb and file transfer return.
pub fn to_device() -> Result<()> {
    std::fs::write(MODE, "peripheral").with_context(|| format!("write peripheral to {MODE}"))?;
    std::thread::sleep(Duration::from_millis(400));
    // The gadget comes back once the controller is a device again, which is
    // not at once: init has to see the role change first.
    let until = std::time::Instant::now() + Duration::from_secs(10);
    let mut last = None;
    while std::time::Instant::now() < until {
        match skyward_sys::usb::set(skyward_sys::usb::resting(), Duration::from_secs(3)) {
            Ok(()) => {
                skyward_sys::kmsg("the port is a device again")?;
                return Ok(());
            }
            Err(e) => {
                last = Some(e);
                std::thread::sleep(Duration::from_millis(300));
            }
        }
    }
    Err(last.unwrap_or_else(|| anyhow::anyhow!("the port did not come back")))
        .context("start the gadget again")
}

/// Put the port back when the recovery starts, whatever an earlier run — or a
/// crash while a stick was mounted — left it as. Without this a recovery that
/// died with the port a host would come back with no adb at all.
pub fn force_device() {
    if !is_host() {
        return;
    }
    let _ = std::fs::write(MODE, "peripheral");
    let _ = skyward_sys::usb::set(skyward_sys::usb::resting(), Duration::from_secs(10));
}
