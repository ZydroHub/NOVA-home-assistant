REPO_DIR := $(shell pwd)

.PHONY: spotify-setup spotify-uninstall

spotify-setup:
	@echo "Setting up Nova Spotify Connect receiver in $(REPO_DIR)"
	chmod +x ./scripts/setup_spotify_device.sh ./scripts/autostart_spotify.sh
	sudo ./scripts/setup_spotify_device.sh
	sed -e "s|__NOVA_PROJECT_ROOT__|$(REPO_DIR)|g" ./scripts/novaspotify-ensure.service.template > /tmp/novaspotify-ensure.service
	sudo cp /tmp/novaspotify-ensure.service /etc/systemd/system/novaspotify-ensure.service
	sudo chmod 644 /etc/systemd/system/novaspotify-ensure.service
	sudo systemctl daemon-reload
	sudo systemctl enable novaspotify-ensure.service
	sudo systemctl start novaspotify-ensure.service
	systemctl status novaspotify-ensure.service --no-pager || true

spotify-uninstall:
	@echo "Stopping novaspotify-ensure.service..."
	-sudo systemctl stop novaspotify-ensure.service
	@echo "Disabling novaspotify-ensure.service from boot..."
	-sudo systemctl disable novaspotify-ensure.service
	@echo "Removing service file..."
	-sudo rm -f /etc/systemd/system/novaspotify-ensure.service
	@echo "Reloading systemd daemon..."
	-sudo systemctl daemon-reload

