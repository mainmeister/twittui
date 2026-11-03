#!/bin/bash
set -e

# If running inside Snap environment
if [ -n "$SNAP" ]; then
    # Ensure SNAP_USER_DATA directory exists
    if [ -n "$SNAP_USER_DATA" ] && [ ! -d "$SNAP_USER_DATA" ]; then
        mkdir -p "$SNAP_USER_DATA"
    fi

    # Set up user configuration if not already present
    if [ -n "$SNAP_USER_DATA" ] && [ ! -f "$SNAP_USER_DATA/.env" ]; then
        if [ -f "$SNAP/.env.example" ]; then
            cp "$SNAP/.env.example" "$SNAP_USER_DATA/.env" 2>/dev/null || true
        fi
    fi

    # Set default download destination if unset
    if [ -z "$TWITCLUBDESTINATION" ] && [ -z "$twitclubdestination" ]; then
        if [ -d "$HOME/Downloads" ]; then
            export TWITCLUBDESTINATION="$HOME/Downloads"
        elif [ -n "$SNAP_USER_DATA" ]; then
            export TWITCLUBDESTINATION="$SNAP_USER_DATA"
        fi
    fi

    # Isolate from incompatible host GTK/Qt desktop module environments
    unset GTK_MODULES
    unset GTK_PATH
    unset GTK3_MODULES
    unset UBUNTU_MENUPROXY
    unset QT_STYLE_OVERRIDE
    unset QT_QPA_PLATFORMTHEME

    # Detect architecture triplet for system libraries
    ARCH_TRIPLET="x86_64-linux-gnu"
    for arch in x86_64-linux-gnu aarch64-linux-gnu arm-linux-gnueabihf; do
        if [ -d "$SNAP/usr/lib/$arch" ]; then
            ARCH_TRIPLET="$arch"
            break
        fi
    done

    export LD_LIBRARY_PATH="$SNAP/usr/lib/$ARCH_TRIPLET:$SNAP/usr/lib:$SNAP/usr/lib/$ARCH_TRIPLET/pulseaudio:${LD_LIBRARY_PATH:-}"
    export GI_TYPELIB_PATH="$SNAP/usr/lib/$ARCH_TRIPLET/girepository-1.0:$SNAP/usr/lib/girepository-1.0:${GI_TYPELIB_PATH:-}"
    export XDG_DATA_DIRS="$SNAP/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
    export GTK_DATA_PREFIX="$SNAP/usr"
    export GSETTINGS_SCHEMA_DIR="$SNAP/usr/share/glib-2.0/schemas:${GSETTINGS_SCHEMA_DIR:-}"

    # Setup GDK Pixbuf loaders cache
    export GDK_PIXBUF_MODULEDIR="$SNAP/usr/lib/$ARCH_TRIPLET/gdk-pixbuf-2.0/2.10.0/loaders"
    if [ -d "$GDK_PIXBUF_MODULEDIR" ]; then
        LOADERS_CACHE="$SNAP_USER_DATA/.loaders.cache"
        if [ -x "$SNAP/usr/lib/$ARCH_TRIPLET/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" ]; then
            "$SNAP/usr/lib/$ARCH_TRIPLET/gdk-pixbuf-2.0/gdk-pixbuf-query-loaders" "$GDK_PIXBUF_MODULEDIR"/* > "$LOADERS_CACHE" 2>/dev/null || true
            if [ -s "$LOADERS_CACHE" ]; then
                export GDK_PIXBUF_MODULE_FILE="$LOADERS_CACHE"
            fi
        fi
    fi

    # Add SNAP Python site-packages and dist-packages to PYTHONPATH
    for py_ver in 3.10 3.11 3.12 3.13 3.14; do
        if [ -d "$SNAP/lib/python${py_ver}/site-packages" ]; then
            export PYTHONPATH="$SNAP/lib/python${py_ver}/site-packages:$PYTHONPATH"
        fi
        if [ -d "$SNAP/usr/lib/python${py_ver}/dist-packages" ]; then
            export PYTHONPATH="$SNAP/usr/lib/python${py_ver}/dist-packages:$PYTHONPATH"
        fi
        if [ -d "$SNAP/usr/lib/python${py_ver}" ]; then
            export PYTHONPATH="$SNAP/usr/lib/python${py_ver}:$PYTHONPATH"
        fi
    done
    export PYTHONPATH="$SNAP:$PYTHONPATH"

    # Search for available python interpreter in snap bundle or system
    if [ -x "$SNAP/usr/bin/python3" ]; then
        PYTHON_BIN="$SNAP/usr/bin/python3"
    elif [ -x "$SNAP/bin/python3" ]; then
        PYTHON_BIN="$SNAP/bin/python3"
    else
        PYTHON_BIN="python3"
    fi

    # Launch application
    if [ -f "$SNAP/main.py" ]; then
        exec "$PYTHON_BIN" "$SNAP/main.py" "$@"
    elif [ -x "$SNAP/bin/twittui" ]; then
        exec "$SNAP/bin/twittui" "$@"
    else
        exec "$PYTHON_BIN" -m main "$@"
    fi
else
    # Non-snap direct execution
    if [ -f "main.py" ]; then
        exec python3 main.py "$@"
    else
        exec python3 -m main "$@"
    fi
fi
