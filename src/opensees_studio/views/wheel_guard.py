"""Keep scrolling from editing unfocused engineering inputs."""

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox


class WheelGuard(QObject):
    def eventFilter(self, obj, event):  # type: ignore[no-untyped-def]
        if isinstance(obj, (QComboBox, QAbstractSpinBox)):
            if event.type() == QEvent.Type.Polish:
                obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
                parent = obj.parentWidget()
                while parent is not None:
                    if isinstance(parent, QAbstractScrollArea):
                        viewport = parent.viewport()
                        forwarded = QWheelEvent(
                            QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                            event.globalPosition(),
                            event.pixelDelta(),
                            event.angleDelta(),
                            event.buttons(),
                            event.modifiers(),
                            event.phase(),
                            event.inverted(),
                        )
                        QApplication.sendEvent(viewport, forwarded)
                        break
                    parent = parent.parentWidget()
                event.accept()
                return True
        return super().eventFilter(obj, event)


def install_wheel_guard() -> None:
    app = QApplication.instance()
    if app is not None and not hasattr(app, "_wheel_guard"):
        app._wheel_guard = WheelGuard(app)
        app.installEventFilter(app._wheel_guard)
