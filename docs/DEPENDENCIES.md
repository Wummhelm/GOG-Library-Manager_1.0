# Dependencies

## Arch Linux
`sudo pacman -S --needed python gtk4 python-gobject python-cairo python-pillow python-requests`

## Debian / Ubuntu
`sudo apt install python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-pil python3-requests`

## Fedora
`sudo dnf install python3 python3-gobject gtk4 python3-cairo python3-pillow python3-requests`

## openSUSE
Core GTK/PyGObject runtime:
`sudo zypper install python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 libgtk-4-1`

See README.md for Pillow/Requests notes.

## Display server
GTK selects Wayland or X11 automatically.
