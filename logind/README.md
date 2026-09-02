# logind

`90-no-lid-suspend.conf` goes in `/etc/systemd/logind.conf.d/`.

This laptop lives closed on a dock with three external screens, and Claude
agents work on it around the clock. Twice a long run was killed by a suspend:
once by the GNOME idle timer (02:44, ten hours lost) and once by the lid
(13:56). Both paths are closed now:

    sudo install -m644 90-no-lid-suspend.conf /etc/systemd/logind.conf.d/
    sudo systemctl restart systemd-logind
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing

On battery the lid still suspends, on purpose.
