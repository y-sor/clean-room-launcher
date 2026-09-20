use cap_std::ambient_authority;
#[cfg(unix)]
use cap_std::fs::MetadataExt;
use cap_std::fs::{Dir, File, Metadata};
use std::fmt;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AdmittedRoot {
    path: PathBuf,
    logical_prefix: String,
}

impl AdmittedRoot {
    pub fn new(path: impl Into<PathBuf>, logical_prefix: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            logical_prefix: logical_prefix.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceRecord {
    pub logical_path: String,
    pub kind: String,
    pub sha256: String,
    pub byte_len: u64,
    pub provenance: String,
    content: Vec<u8>,
}

impl SourceRecord {
    pub fn content(&self) -> &[u8] {
        &self.content
    }
}

#[derive(Debug)]
pub enum CoreError {
    Io { path: PathBuf, source: io::Error },
    Refused { code: &'static str, path: PathBuf },
    InvalidLogicalPrefix(String),
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io { path, source } => write!(f, "IO_ERROR:{}:{source}", path.display()),
            Self::Refused { code, path } => write!(f, "{code}:{}", path.display()),
            Self::InvalidLogicalPrefix(prefix) => write!(f, "INVALID_LOGICAL_PREFIX:{prefix}"),
        }
    }
}

impl std::error::Error for CoreError {}

pub fn inventory(admitted: &[AdmittedRoot]) -> Result<Vec<SourceRecord>, CoreError> {
    inventory_impl(admitted, &mut |_| {})
}

pub(crate) fn inventory_capability(
    root: &Dir,
    logical_prefix: &str,
) -> Result<Vec<SourceRecord>, CoreError> {
    inventory_capability_impl(root, logical_prefix, &mut |_| {})
}

fn inventory_capability_impl(
    root: &Dir,
    logical_prefix: &str,
    observer: &mut dyn FnMut(&Path),
) -> Result<Vec<SourceRecord>, CoreError> {
    validate_prefix(logical_prefix)?;
    let dir = root.try_clone().map_err(|source| CoreError::Io {
        path: PathBuf::from("<admitted-capability>"),
        source,
    })?;
    let mut records = Vec::new();
    walk(&dir, Path::new(""), logical_prefix, &mut records, observer)?;
    records.sort_by(|a, b| a.logical_path.as_bytes().cmp(b.logical_path.as_bytes()));
    Ok(records)
}

#[cfg(test)]
pub(crate) fn inventory_capability_with_observer(
    root: &Dir,
    logical_prefix: &str,
    observer: &mut dyn FnMut(&Path),
) -> Result<Vec<SourceRecord>, CoreError> {
    inventory_capability_impl(root, logical_prefix, observer)
}

#[cfg(test)]
pub(crate) fn inventory_with_observer(
    admitted: &[AdmittedRoot],
    observer: &mut dyn FnMut(&Path),
) -> Result<Vec<SourceRecord>, CoreError> {
    inventory_impl(admitted, observer)
}

fn inventory_impl(
    admitted: &[AdmittedRoot],
    observer: &mut dyn FnMut(&Path),
) -> Result<Vec<SourceRecord>, CoreError> {
    let mut records = Vec::new();
    for root in admitted {
        validate_prefix(&root.logical_prefix)?;
        refuse_symlink(&root.path)?;
        let root_handle = Dir::open_ambient_dir(&root.path, ambient_authority())
            .map_err(|source| classify_open_error(&root.path, source))?;
        walk(
            &root_handle,
            Path::new(""),
            &root.logical_prefix,
            &mut records,
            observer,
        )?;
    }
    records.sort_by(|left, right| {
        left.logical_path
            .as_bytes()
            .cmp(right.logical_path.as_bytes())
    });
    Ok(records)
}

fn validate_prefix(prefix: &str) -> Result<(), CoreError> {
    if prefix.is_empty()
        || prefix.starts_with('/')
        || prefix
            .split('/')
            .any(|part| part.is_empty() || part == "." || part == "..")
    {
        return Err(CoreError::InvalidLogicalPrefix(prefix.to_owned()));
    }
    Ok(())
}

fn walk(
    directory: &Dir,
    relative_parent: &Path,
    prefix: &str,
    records: &mut Vec<SourceRecord>,
    observer: &mut dyn FnMut(&Path),
) -> Result<(), CoreError> {
    let mut entries = directory
        .entries()
        .map_err(|source| io_error(relative_parent, source))?
        .map(|entry| entry.map_err(|source| io_error(relative_parent, source)))
        .collect::<Result<Vec<_>, _>>()?;
    entries.sort_by(|left, right| {
        left.file_name()
            .as_encoded_bytes()
            .cmp(right.file_name().as_encoded_bytes())
    });
    for entry in entries {
        let relative = relative_parent.join(entry.file_name());
        let logical_path = join_logical(prefix, &relative)?;
        let file_type = entry
            .file_type()
            .map_err(|source| classify_open_error(&relative, source))?;
        if file_type.is_symlink() {
            return Err(CoreError::Refused {
                code: "SYMLINK_ESCAPE",
                path: relative,
            });
        }
        if file_type.is_dir() {
            let child = entry
                .open_dir()
                .map_err(|source| classify_open_error(&relative, source))?;
            walk(&child, &relative, prefix, records, observer)?;
        } else if file_type.is_file() {
            let child = entry
                .open()
                .map_err(|source| classify_open_error(&relative, source))?;
            let metadata = child
                .metadata()
                .map_err(|source| io_error(&relative, source))?;
            #[cfg(unix)]
            if metadata.mode() & 0o444 == 0 {
                return Err(CoreError::Refused {
                    code: "UNREADABLE_FILE",
                    path: relative,
                });
            }
            records.push(read_record(
                child,
                &relative,
                metadata,
                logical_path,
                observer,
            )?);
        } else {
            return Err(CoreError::Refused {
                code: "SPECIAL_FILE",
                path: relative,
            });
        }
    }
    Ok(())
}

fn join_logical(prefix: &str, relative: &Path) -> Result<String, CoreError> {
    let suffix = relative
        .to_str()
        .ok_or_else(|| CoreError::Refused {
            code: "INVALID_UTF8_PATH",
            path: relative.to_owned(),
        })?
        .replace('\\', "/");
    if suffix.is_empty() {
        Ok(prefix.to_owned())
    } else {
        Ok(format!("{prefix}/{suffix}"))
    }
}

fn read_record(
    mut file: File,
    path: &Path,
    before: Metadata,
    logical_path: String,
    observer: &mut dyn FnMut(&Path),
) -> Result<SourceRecord, CoreError> {
    observer(path);
    let mut bytes = Vec::with_capacity(before.len() as usize);
    file.read_to_end(&mut bytes)
        .map_err(|source| io_error(path, source))?;
    let after = file.metadata().map_err(|source| io_error(path, source))?;
    if !same_file_state(&before, &after) || after.len() != bytes.len() as u64 {
        return Err(CoreError::Refused {
            code: "PATH_RACE",
            path: path.to_owned(),
        });
    }
    Ok(SourceRecord {
        logical_path,
        kind: "file".to_owned(),
        sha256: sha256_hex(&bytes),
        byte_len: bytes.len() as u64,
        provenance: "admitted-root".to_owned(),
        content: bytes,
    })
}

fn io_error(path: &Path, source: io::Error) -> CoreError {
    CoreError::Io {
        path: path.to_owned(),
        source,
    }
}

fn refuse_symlink(path: &Path) -> Result<(), CoreError> {
    let metadata = fs::symlink_metadata(path).map_err(|source| io_error(path, source))?;
    if metadata.file_type().is_symlink() {
        return Err(CoreError::Refused {
            code: "SYMLINK_ESCAPE",
            path: path.to_owned(),
        });
    }
    Ok(())
}

fn classify_open_error(path: &Path, source: io::Error) -> CoreError {
    let code = if source.kind() == io::ErrorKind::PermissionDenied {
        "UNREADABLE_FILE"
    } else {
        "PATH_RACE"
    };
    CoreError::Refused {
        code,
        path: path.to_owned(),
    }
}

#[cfg(unix)]
fn same_file_state(left: &Metadata, right: &Metadata) -> bool {
    left.dev() == right.dev()
        && left.ino() == right.ino()
        && left.len() == right.len()
        && left.mtime() == right.mtime()
        && left.mtime_nsec() == right.mtime_nsec()
        && left.ctime() == right.ctime()
        && left.ctime_nsec() == right.ctime_nsec()
}

#[cfg(not(unix))]
fn same_file_state(left: &Metadata, right: &Metadata) -> bool {
    left.len() == right.len() && left.modified().ok() == right.modified().ok()
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let mut h: [u32; 8] = [
        0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab,
        0x5be0cd19,
    ];
    let bit_len = (bytes.len() as u64) * 8;
    let mut data = bytes.to_vec();
    data.push(0x80);
    while !(data.len() + 8).is_multiple_of(64) {
        data.push(0);
    }
    data.extend_from_slice(&bit_len.to_be_bytes());
    for chunk in data.chunks_exact(64) {
        let mut w = [0u32; 64];
        for (i, word) in w[..16].iter_mut().enumerate() {
            *word = u32::from_be_bytes([
                chunk[i * 4],
                chunk[i * 4 + 1],
                chunk[i * 4 + 2],
                chunk[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let k: [u32; 64] = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
            0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
            0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
            0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
            0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
            0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
            0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
            0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
            0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
            0xc67178f2,
        ];
        let mut a = h[0];
        let mut b = h[1];
        let mut c = h[2];
        let mut d = h[3];
        let mut e = h[4];
        let mut f = h[5];
        let mut g = h[6];
        let mut i = h[7];
        for t in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = i
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(k[t])
                .wrapping_add(w[t]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);
            i = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        h[0] = h[0].wrapping_add(a);
        h[1] = h[1].wrapping_add(b);
        h[2] = h[2].wrapping_add(c);
        h[3] = h[3].wrapping_add(d);
        h[4] = h[4].wrapping_add(e);
        h[5] = h[5].wrapping_add(f);
        h[6] = h[6].wrapping_add(g);
        h[7] = h[7].wrapping_add(i);
    }
    h.iter().map(|word| format!("{word:08x}")).collect()
}

#[cfg(test)]
#[path = "../../tests/core/inventory.rs"]
mod tests;
