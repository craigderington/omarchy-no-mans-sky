pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: root
    readonly property string font: "JetBrainsMono Nerd Font"
    readonly property string sans: font
    property bool frozen: false
    property var saved: ({ special: { background: "#111820", foreground: "#e2e8ef" }, colors: {
        color0: "#111820", color1: "#d2776b", color2: "#9fb99a", color3: "#e1b774",
        color4: "#78a9c5", color5: "#b4a0c8", color6: "#8fc5c3", color7: "#e2e8ef",
        color8: "#617181", color9: "#e1b774", color10: "#adc9a6", color11: "#f0cf95",
        color12: "#98c5df", color13: "#a8c8db", color14: "#a9dbd6", color15: "#f2f5f7"
    } })
    readonly property color bg: saved.special.background
    readonly property color fg: saved.special.foreground
    readonly property color accent: c(9, "#e1b774")
    readonly property color accent2: c(13, "#a8c8db")
    readonly property color dim: alpha(fg, 0.5)
    readonly property color faint: alpha(fg, 0.14)
    readonly property color edge: alpha(accent, 0.35)
    readonly property int bar: 24
    readonly property var settle: [0.2, 0.9, 0.3, 1, 1, 1]
    property bool animates: true
    function ms(value) { return animates ? Math.round(value) : 0 }
    function c(index, fallback) { return saved.colors["color" + index] || fallback }
    function slotOf(role) { return role === "accent2" ? 13 : 9 }
    function alpha(value, a) { const c = Qt.color(value); return Qt.rgba(c.r, c.g, c.b, a) }
    function mix(a, b, t) { a = Qt.color(a); b = Qt.color(b); return Qt.rgba(a.r + (b.r-a.r)*t, a.g + (b.g-a.g)*t, a.b + (b.b-a.b)*t, 1) }
    function readable(value) { return Qt.color(value) }

    Process {
        id: motion
        command: ["hyprctl", "-j", "getoption", "animations:enabled"]
        stdout: StdioCollector {
            onStreamFinished: { try { const v = JSON.parse(text); root.animates = v.bool ?? v.int !== 0 } catch (e) {} }
        }
    }
    Component.onCompleted: motion.running = true
}
