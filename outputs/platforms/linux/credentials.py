"""Linux credential storage: SecretService through keyring, 0600 file as fallback."""
from platforms.keyring_store import KeyringCredentialStore

CredentialStore = KeyringCredentialStore
