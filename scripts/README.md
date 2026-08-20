Setup scripts for Raspberry Pi

setup_spotify_device.sh
- Purpose: Installs and configures Raspotify (librespot) and sets the device name to "NOVA".
- Usage (on the Pi):
  - Pull the repo changes: `git pull`
  - Make the script executable and run it as root:
    ```bash
    chmod +x scripts/setup_spotify_device.sh
    sudo ./scripts/setup_spotify_device.sh
    ```

Notes
- The script will create a backup of the existing Raspotify config at `/etc/raspotify/conf.bak.<timestamp>`.
- If you don't see the device in Spotify, ensure the Pi and your Spotify client are on the same network and that Spotify is running on your client.

Autostart (run on every boot)
- The repo includes `scripts/autostart_spotify.sh`, a small idempotent script that ensures Raspotify is installed, configured (DEVICE_NAME="NOVA", BITRATE=320), enabled and restarted.
- To make the autostart script run at every boot, install the provided systemd unit template. Replace the path in the template if your repo lives elsewhere.

Install the unit (on the Pi):
```bash
# copy unit file to systemd
sudo cp scripts/novaspotify-ensure.service.template /etc/systemd/system/novaspotify-ensure.service
# edit ExecStart in /etc/systemd/system/novaspotify-ensure.service if needed to point to the full path
sudo systemctl daemon-reload
sudo systemctl enable novaspotify-ensure.service
sudo systemctl start novaspotify-ensure.service
```

You can check status with:
```bash
systemctl status novaspotify-ensure.service
journalctl -u novaspotify-ensure.service -n 200 --no-pager
```
