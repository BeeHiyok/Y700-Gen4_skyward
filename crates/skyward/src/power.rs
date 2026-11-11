//! The charging and port stack.
//!
//! The PMIC's charger and the Type-C port controller are not driven by Linux
//! directly: they run firmware on the ADSP, reached through `pmic_glink`. A
//! recovery leaves the ADSP offline, and then nothing charges — the port draws
//! no current at all, whatever the cable — and the port can never be a host,
//! so a USB stick is never powered. Starting the ADSP from the recovery brings
//! the whole stack up: `power_supply` fills, the charger runs, and the port
//! controller can switch roles.
//!
//! Starting it resets the USB port, which takes adb down with it, so the port
//! is given back to the gadget afterwards.

use anyhow::{bail, Context, Result};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// Where the charger and port controller appear once their firmware runs.
const SUPPLY: &str = "/sys/class/power_supply";

/// Whether the stack is up: the charger registers its supplies when it is.
pub fn up() -> bool {
    std::fs::read_dir(SUPPLY).map(|mut entries| entries.next().is_some()).unwrap_or(false)
}

/// The ADSP's remoteproc, found by the name of its device rather than by the
/// number the class gives it: the numbers depend on the order the subsystems
/// happen to register in, and writing "start" to the modem's would do nothing
/// useful.
fn adsp() -> Option<PathBuf> {
    let devices = std::fs::read_dir("/sys/bus/platform/devices").ok()?;
    for entry in devices.flatten() {
        if !entry.file_name().to_string_lossy().contains("remoteproc-adsp") {
            continue;
        }
        let inside = entry.path().join("remoteproc");
        for rproc in std::fs::read_dir(&inside).ok()?.flatten() {
            if rproc.path().join("state").is_file() {
                return Some(rproc.path());
            }
        }
    }
    None
}

/// Where the recovery keeps a note of what it did to the port: the kernel log
/// does not survive the reboot that a port with no adb forces on the user, and
/// this is the only way to see what happened on the boot that lost it. The
/// metadata partition is mounted by both the recovery and the system, and
/// survives a reboot, so the note can be read from either.
const DIARY: &[&str] = &[
    "/mnt/vendor/persist/skyward-power.log",
    "/external_sd/skyward-power.log",
    "/data/media/skyward-power.log",
];

/// Note one step of the port's story where it will still be readable after a
/// reboot.
fn note(line: &str) {
    use std::io::Write;
    let _ = skyward_sys::kmsg(line);
    for at in DIARY {
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(at) {
            let _ = writeln!(f, "{line}");
            return;
        }
    }
}

/// Everything the port says about itself, for the diary.
fn port_facts() -> String {
    let mut out = String::new();
    for (label, path) in [
        ("ucsi-port0-data_role", "/sys/class/typec/port0/data_role"),
        ("ucsi-port0-power_role", "/sys/class/typec/port0/power_role"),
        ("ucsi-port0-mode", "/sys/class/typec/port0/power_operation_mode"),
        ("usb-online", "/sys/class/power_supply/usb/online"),
        ("usb-suspend", "/sys/class/power_supply/usb/input_suspend"),
        ("usb-type", "/sys/class/power_supply/usb/real_type"),
        ("gadget-UDC", "/config/usb_gadget/g1/UDC"),
        ("ssusb-mode", "/sys/bus/platform/devices/a600000.ssusb/mode"),
        ("role-switch", "/sys/class/usb_role/a600000.ssusb-role-switch/role"),
    ] {
        let value = std::fs::read_to_string(path).map(|v| v.trim().to_string()).unwrap_or_else(|_| "?".into());
        out.push_str(&format!("{label}={value} "));
    }
    let udcs: Vec<String> = std::fs::read_dir("/sys/class/udc")
        .map(|d| d.flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect())
        .unwrap_or_default();
    out.push_str(&format!("udcs={udcs:?}"));
    out
}

/// Bring the stack up in the background, trying until the firmware is there.
///
/// The recovery starts before its init has mounted the firmware partition,
/// and the ADSP cannot boot without it, so this waits for the partition and
/// tries again. It runs off the main thread because starting the ADSP resets
/// the USB port, and the pages should not wait on that.
pub fn start_soon() {
    std::thread::spawn(|| {
        let until = Instant::now() + Duration::from_secs(120);
        while Instant::now() < until {
            if up() {
                return;
            }
            // The firmware partition holds image/ once init has mounted it.
            if Path::new(FIRMWARE).join("image").is_dir() {
                if start().is_ok() {
                    return;
                }
            }
            std::thread::sleep(Duration::from_secs(2));
        }
        let _ = skyward_sys::kmsg("the charger did not come up; this recovery will not charge");
    });
}

/// Bring the stack up if it is not, and give the port back to the gadget
/// afterwards. Nothing to do on a phone whose recovery already runs it.
pub fn start() -> Result<()> {
    if up() {
        return Ok(());
    }
    // The kernel asks the ADSP to boot at the very start, before anything is
    // mounted, and the request fails with no firmware to read. The recovery
    // has the firmware partition by then, so it is mounted here and the boot
    // asked for again.
    mount_firmware()?;
    let Some(adsp) = adsp() else {
        bail!("this phone has no ADSP to start, so nothing would charge");
    };
    let state = adsp.join("state");
    note(&format!("starting the ADSP for the charger and the port; before: {}", port_facts()));
    std::fs::write(&state, "start").with_context(|| format!("start {}", state.display()))?;

    // The firmware takes a few seconds to come up, and the charger registers
    // its supplies once it does.
    let until = Instant::now() + Duration::from_secs(20);
    while Instant::now() < until {
        if up() {
            let supplies: Vec<String> = std::fs::read_dir(SUPPLY)
                .map(|d| d.flatten().map(|e| e.file_name().to_string_lossy().into_owned()).collect())
                .unwrap_or_default();
            note(&format!("the charger is up: supplies={supplies:?} {}", port_facts()));
            give_the_port_back();
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    note(&format!("the charger did not come up: {}", port_facts()));
    // Up or not, the port has to come back: a recovery with no adb is worse
    // than one that does not charge.
    give_the_port_back();
    bail!("the charger did not come up within 20 s")
}

/// The partition the ADSP's firmware is read from.
const FIRMWARE: &str = "/firmware";

/// Mount the firmware partition unless it is already there. The ADSP's
/// request for its firmware is served from userspace through ueventd, so it
/// has to be mounted before the request, not after.
fn mount_firmware() -> Result<()> {
    let at = Path::new(FIRMWARE);
    if skyward_block::mount::is_mount_point(at)? {
        return Ok(());
    }
    std::fs::create_dir_all(at).with_context(|| format!("make {}", at.display()))?;
    let partition = Path::new("/dev/block/by-name/firmware");
    skyward_block::mount::mount_ro(partition, at).context("mount /firmware")?;
    Ok(())
}

/// Ask init for the gadget again, since starting the stack reset the port.
///
/// It has to go through "none" first: writing the value a property already
/// holds changes nothing, so init would not rebuild the gadget, and waiting
/// for a state that never changed would report success while adb stayed dead.
/// The port itself is asked for data too: the controller came up for a cable
/// it wants to charge from, and nothing told it that data is wanted.
fn give_the_port_back() {
    note(&format!("after the stack: {}", port_facts()));
    let _ = std::fs::write("/sys/bus/platform/devices/a600000.ssusb/mode", "peripheral");
    let _ = std::fs::write("/sys/class/typec/port0/data_role", "device");
    let _ = std::fs::write("/sys/class/typec/port0-data-role", "device");
    let _ = std::fs::write("/sys/class/power_supply/usb/input_suspend", "0");
    for attempt in 0..8 {
        // A controller that lost its gadget needs the binding back, which init
        // does on its own most of the time; this is for the times it does not.
        if let Ok(udcs) = std::fs::read_dir("/sys/class/udc") {
            if let Some(name) = udcs.flatten().next().map(|e| e.file_name().to_string_lossy().into_owned()) {
                let _ = std::fs::write("/config/usb_gadget/g1/UDC", "");
                std::thread::sleep(Duration::from_millis(200));
                let _ = std::fs::write("/config/usb_gadget/g1/UDC", &name);
            }
        }
        let _ = skyward_sys::usb::set("none", Duration::from_secs(4));
        if skyward_sys::usb::set(skyward_sys::usb::resting(), Duration::from_secs(6)).is_ok() {
            note(&format!("adb is back on the port after {attempt} tries: {}", port_facts()));
            return;
        }
        note(&format!("try {attempt}: adb not back: {}", port_facts()));
        std::thread::sleep(Duration::from_millis(700));
    }
    note(&format!("adb did not come back: {}", port_facts()));
}

/// The battery's charge, as a percentage, once the stack is up.
pub fn capacity() -> Option<u8> {
    let text = std::fs::read_to_string(Path::new(SUPPLY).join("battery/capacity")).ok()?;
    text.trim().parse().ok()
}
