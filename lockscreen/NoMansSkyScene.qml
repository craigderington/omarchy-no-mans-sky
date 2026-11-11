import QtQuick
import qs.Commons as Commons

Item {
    id: root
    property real inputTop: height / 2 + 50
    property real inputHeight: 60
    readonly property bool compact: height < 700 || width < 700
    readonly property real margin: compact ? 24 : 48
    readonly property color amber: "#e1b774"
    readonly property color ink: "#111820"
    property date now: new Date()

    Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }
    Timer { interval: 1000; running: root.visible; repeat: true; onTriggered: root.now = new Date() }

    // A still from our landscape renderer: no window capture or animation
    // continues behind the password prompt, even on a battery-powered laptop.
    Image {
        anchors.fill: parent
        source: "landscape.png"
        fillMode: Image.PreserveAspectCrop
        sourceSize: Qt.size(root.width, root.height)
        cache: true
    }
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0; color: "#b0080d13" }
            GradientStop { position: 0.42; color: "#88080d13" }
            GradientStop { position: 0.7; color: "#b0111820" }
            GradientStop { position: 1; color: "#f0080d13" }
        }
    }

    component Caption: Text {
        textFormat: Text.PlainText
        color: root.amber
        font.family: Commons.Style.font.family
        font.pixelSize: 10
        font.letterSpacing: 2
    }

    Column {
        x: root.margin
        y: root.margin
        spacing: 9
        Caption { text: "OMARCHY / NO MAN’S SKY" }
        Rectangle { width: 36; height: 2; color: root.amber }
    }
    Caption {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: root.margin
        visible: root.width > 760
        text: strings.t("lock.sessionSecured")
        color: "#c5d2df"
    }

    // The Atlas diamond, clock, and prompt share an axis. Compact mode fits
    // the 1024×600 auxiliary display without cropping any authentication UI.
    Column {
        width: Math.min(460, root.width - 48)
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.inputTop - height - (root.compact ? 22 : 30)
        spacing: root.compact ? 10 : 16

        Item {
            width: parent.width
            height: root.compact ? 44 : 64
            Canvas {
                anchors.centerIn: parent
                width: root.compact ? 42 : 58
                height: width
                onPaint: {
                    const c = getContext("2d")
                    c.reset()
                    const m = width / 2
                    c.strokeStyle = root.amber
                    c.lineWidth = 1
                    c.beginPath()
                    c.moveTo(m, 1); c.lineTo(width - 1, m)
                    c.lineTo(m, height - 1); c.lineTo(1, m); c.closePath(); c.stroke()
                    c.globalAlpha = 0.4
                    c.beginPath()
                    c.moveTo(m, 9); c.lineTo(width - 9, m)
                    c.lineTo(m, height - 9); c.lineTo(9, m); c.closePath(); c.stroke()
                    c.globalAlpha = 1
                    c.fillStyle = root.amber
                    c.beginPath(); c.arc(m, m, 3, 0, Math.PI * 2); c.fill()
                }
            }
        }
        Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.now.toLocaleTimeString(Qt.locale(Commons.I18n.formatLocale), "HH:mm")
            color: "#f2f5f7"
            font.family: Commons.Style.font.family
            font.pixelSize: root.compact ? 56 : 76
            font.weight: Font.Light
            horizontalAlignment: Text.AlignHCenter
        }
        Caption {
            width: parent.width
            text: root.now.toLocaleDateString(Qt.locale(Commons.I18n.formatLocale), "dddd, d MMMM").toLocaleUpperCase()
            color: "#c5d2df"
            font.letterSpacing: 1
            horizontalAlignment: Text.AlignHCenter
        }
        Caption {
            width: parent.width
            topPadding: root.compact ? 7 : 12
            text: strings.t("lock.resumeJourney")
            horizontalAlignment: Text.AlignHCenter
        }
    }

    Caption {
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.inputTop + root.inputHeight + 54
        visible: y + height < root.height - 70
        text: strings.t("lock.unlockHint")
        color: "#a1afbd"
        font.letterSpacing: 0.5
    }
    Rectangle {
        x: root.margin
        y: root.height - root.margin - 28
        width: root.width - root.margin * 2
        height: 1
        color: "#40e1b774"
    }
    Caption {
        x: root.margin
        anchors.bottom: parent.bottom
        anchors.bottomMargin: root.margin
        text: strings.t("lock.traveller")
        color: "#81919f"
    }
    Caption {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: root.margin
        text: "16 / 16 / 16"
        font.letterSpacing: 3
    }
}
