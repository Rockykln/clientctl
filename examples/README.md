# Example deployment files

Pick the integration that matches how you want to run clientctl. Replace
every `<PATH-TO-CLIENTCTL>` placeholder with your absolute clone path
(e.g. `/home/alice/clientctl`) before installing.

| File | What it does | Use when |
|------|--------------|----------|
| [`clientctl.desktop`](clientctl.desktop) | KDE / freedesktop application launcher | You want a double-click icon on the desktop or in the app menu. Runs in a terminal so the login code is visible. |
| [`clientctl.service`](clientctl.service) | systemd user service | You want clientctl to start automatically on login and run headless in the background. |
| [`clientctl-tunnel.service`](clientctl-tunnel.service) | systemd user service for the Cloudflare tunnel | You're using `clientctl.service` AND a Cloudflare tunnel. Tied to the main service via `Requires=`. |

## Quick install — desktop icon

```bash
# xdg-user-dir resolves to the localised Desktop folder
# (~/Desktop, ~/Schreibtisch, ~/Bureau, …) so this works on every locale.
DESKTOP_DIR="$(xdg-user-dir DESKTOP)"
cp examples/clientctl.desktop "$DESKTOP_DIR/clientctl.desktop"
sed -i "s|<PATH-TO-CLIENTCTL>|$PWD|g" "$DESKTOP_DIR/clientctl.desktop"
chmod +x "$DESKTOP_DIR/clientctl.desktop"
# KDE: right-click the file -> "Allow Executing as Program"
# (or run: gio set "$DESKTOP_DIR/clientctl.desktop" metadata::trusted true)
```

## Quick install — systemd user service

```bash
mkdir -p ~/.config/systemd/user
cp examples/clientctl.service ~/.config/systemd/user/
sed -i "s|<PATH-TO-CLIENTCTL>|$PWD|g" ~/.config/systemd/user/clientctl.service

# Optional: also install the tunnel companion
cp examples/clientctl-tunnel.service ~/.config/systemd/user/
sed -i "s|<PATH-TO-CLIENTCTL>|$PWD|g" ~/.config/systemd/user/clientctl-tunnel.service

systemctl --user daemon-reload
systemctl --user enable --now clientctl.service
# Optional: also enable the tunnel
systemctl --user enable --now clientctl-tunnel.service

# Watch logs (the login code is in here)
journalctl --user -u clientctl.service -f
```

## Why two services?

The split lets you run clientctl on the LAN only (without the tunnel)
or, equally, run the tunnel against a different backend during testing.
If you always want both together, just enable both — `clientctl-tunnel`
will refuse to start unless `clientctl` is up because of the
`Requires=clientctl.service` line.

## Stopping

```bash
systemctl --user stop clientctl-tunnel.service clientctl.service
systemctl --user disable clientctl-tunnel.service clientctl.service
```

For the desktop launcher, just close the terminal window — `start.sh`
has a trap that cleans up the server and tunnel on exit.
