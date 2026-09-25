[ -f ~/.bashrc ] && . ~/.bashrc
# The server's own screen: autologin on tty1 shows the motivation page. Ctrl+Alt+F2 = a normal console.
if [ "$(tty)" = /dev/tty1 ] && [ -z "$WAYLAND_DISPLAY" ] && [ ! -f ~/.config/server-kiosk-off ]; then
  ~/bin/server-kiosk
  sleep 3
  logout
fi
