pragma Singleton
import QtQuick
import Quickshell

// Compatibility for the upstream renderer; settings stay within this project.
Singleton {
    property var values: ({ "space.parallax": 0.65 })
    function set(key, value) { values = Object.assign({}, values, { [key]: value }) }
}
