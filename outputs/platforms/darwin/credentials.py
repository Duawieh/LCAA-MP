"""macOS credential storage: Keychain through keyring, 0600 file as fallback."""
from platforms.keyring_store import KeyringCredentialStore

# Writing a password through the `security` CLI would put it in argv, where any
# local process can read it, so the fallback is a 0600 file instead.
CredentialStore = KeyringCredentialStore
