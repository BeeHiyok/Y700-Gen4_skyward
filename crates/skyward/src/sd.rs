//! The phone's own SD card: a recovery's table names no card, so the one
//! the kernel reports is found here and mounted where the device's
//! configuration says it should be shown.

use anyhow::{bail, Context, Result};
use skyward_config::Sd;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

/// The filesystems a card may hold, the two the cards of phones are
/// formatted as first. The kernel is asked for each in turn and only its
/// answer for "not this filesystem" moves on to the next.
const FILESYSTEMS: [&str; 4] = ["vfat", "exfat", "ext4", "f2fs"];

/// The block devices of the cards the kernel reports, partitions first: a
/// card holding one partition is mounted through that partition, and a card
/// formatted whole is mounted through the device itself.
fn cards() -> Result<Vec<PathBuf>> {
    let mut partitions = Vec::new();
    let mut disks = Vec::new();
    let listing = match std::fs::read_dir("/sys/class/block") {
        Ok(listing) => listing,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(e).context("read /sys/class/block"),
    };
    for entry in listing {
        let entry = entry.context("read /sys/class/block")?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        // The card reader's own boot and replay-protected areas are not the
        // card: mmcblk0boot0, mmcblk0boot1, mmcblk0rpmb.
        if !name.starts_with("mmcblk") || name.contains("boot") || name.contains("rpmb") {
            continue;
        }
        let at = entry.path();
        let device = Path::new("/dev/block").join(name);
        if at.join("partition").exists() {
            partitions.push(device);
        } else {
            disks.push(device);
        }
    }
    partitions.sort();
    disks.sort();
    partitions.extend(disks);
    Ok(partitions)
}

/// Mount `card` at `at` with the first filesystem that takes it, writable
/// where the kernel allows it and read-only otherwise.
fn mount_one(card: &Path, at: &Path) -> Result<&'static str> {
    let mut refused = Vec::new();
    for options in [Vec::new(), vec!["ro".to_string()]] {
        for filesystem in FILESYSTEMS {
            match skyward_block::mount::mount(card, at, filesystem, &options) {
                Ok(()) => return Ok(filesystem),
                Err(e) => refused.push(format!("{filesystem}: {e}")),
            }
        }
    }
    bail!("{}", refused.join("; "))
}

/// Mount the phone's SD card where the configuration says it is shown, and
/// say in the kernel log what was found. A phone with no card is not an
/// error: the recovery works without one.
pub fn mount(cfg: &Sd) -> Result<()> {
    let at = Path::new(&cfg.mount);
    if skyward_block::mount::is_mount_point(at)? {
        return Ok(());
    }
    let until = Instant::now() + Duration::from_secs(cfg.wait_seconds.clamp(1, 120));
    loop {
        let found = cards()?;
        for card in &found {
            std::fs::create_dir_all(at).with_context(|| format!("make {}", at.display()))?;
            match mount_one(card, at) {
                Ok(filesystem) => {
                    skyward_sys::kmsg(&format!(
                        "the SD card {} is mounted on {} as {filesystem}",
                        card.display(),
                        at.display()
                    ))?;
                    return Ok(());
                }
                Err(e) => {
                    skyward_sys::kmsg(&format!("{} cannot be mounted as a card: {e}", card.display()))?;
                }
            }
        }
        if Instant::now() >= until {
            break;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    skyward_sys::kmsg(&format!("no SD card was found to mount on {}", at.display()))?;
    Ok(())
}
