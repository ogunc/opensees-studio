"""One form for every signature material (``core/materials/library.py``).

The rows come from the model's fields in OpenSees order: a number is a
``FloatField``, a whole number a spin box, a fixed set of choices a combo box, a
wrapped material a combo of the project's materials, several wrapped materials a
checklist, and a list of points a two-column table. Each row's tooltip is the
field's description. ``form_class(model)`` makes the subclass the Material
Library registers per type.
"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from opensees_studio.core import Project
from opensees_studio.core.materials.library import SignatureMaterial
from opensees_studio.views.dialogs.material_forms import MaterialFormBase
from opensees_studio.views.float_field import FloatField

_SKIP = ("id", "name", "type")


def _choices(annotation: Any) -> tuple[Any, ...] | None:
    return get_args(annotation) if get_origin(annotation) is Literal else None


class SignatureMaterialForm(MaterialFormBase):
    """Rows built from ``model``'s fields; ``project`` fills the wrapped-material choices."""

    model: type[Any] = SignatureMaterial
    #: Values for fields the model requires (it has no default for them).
    defaults: dict[str, Any] = {}  # noqa: RUF012 - read-only per subclass
    needs_project = True

    def __init__(self, parent: QWidget | None = None, *, project: Project | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self.widgets: dict[str, QWidget] = {}
        defaults = self._defaults()
        for name, info in self.model.model_fields.items():
            if name in _SKIP:
                continue
            widget = self._widget(name, info.annotation, getattr(defaults, name))
            widget.setToolTip(info.description or "")
            label = f"{name} — {info.description}:" if info.description else f"{name}:"
            self._layout.addRow(label, widget)
            self.widgets[name] = widget

    # ── defaults and widgets ────────────────────────────────────────
    def _materials(self) -> list[Any]:
        return list(self._project.materials) if self._project is not None else []

    def _defaults(self) -> Any:
        extra: dict[str, Any] = dict(self.defaults)
        others = [m.id for m in self._materials()]
        if "material_id" in self.model.model_fields and others:
            extra["material_id"] = others[0]
        if "material_ids" in self.model.model_fields:
            extra["material_ids"] = others[:2] or [1]
        return self.model(id=1, **extra)

    def _widget(self, name: str, annotation: Any, value: Any) -> QWidget:
        choices = _choices(annotation)
        if name.endswith("material_id"):
            combo = QComboBox()
            for m in self._materials():
                combo.addItem(f"#{m.id} {m.name or m.type} [{m.type}]", m.id)
            self._set_combo(combo, value)
            return combo
        if name.endswith("material_ids"):
            listing = QListWidget()
            for m in self._materials():
                item = QListWidgetItem(f"#{m.id} {m.name or m.type} [{m.type}]")
                item.setData(Qt.ItemDataRole.UserRole, m.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                listing.addItem(item)
            self._set_ids(listing, value)
            return listing
        if choices is not None:
            combo = QComboBox()
            for choice in choices:
                combo.addItem(str(choice), choice)
            self._set_combo(combo, value)
            return combo
        if (
            isinstance(value, list)
            and name not in ("factors",)
            and (not value or isinstance(value[0], tuple))
        ):
            table = QTableWidget(0, 2)
            headers = ["Force", "Deformation"] if name.endswith("_env") else ["Strain", "Stress"]
            table.setHorizontalHeaderLabels(headers)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self._set_points(table, value)
            return table
        if name == "factors":
            edit = QLineEdit(", ".join(f"{v:g}" for v in value))
            edit.setPlaceholderText("one factor per material, or empty for 1")
            return edit
        if annotation is int or str(annotation) in ("PositiveInt", "int"):
            spin = QSpinBox()
            spin.setRange(1, 10_000)
            spin.setValue(int(value))
            return spin
        field = FloatField()
        field.setRange(-1e300, 1e300)
        field.setValue(float(value))
        return field

    @staticmethod
    def _set_combo(combo: QComboBox, value: Any) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _set_ids(listing: QListWidget, ids: list[int]) -> None:
        for row in range(listing.count()):
            item = listing.item(row)
            checked = item.data(Qt.ItemDataRole.UserRole) in ids
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    @staticmethod
    def _set_points(table: QTableWidget, points: list[tuple[float, float]]) -> None:
        table.setRowCount(len(points) + 3)  # spare rows to type more points
        for r, (strain, stress) in enumerate(points):
            table.setItem(r, 0, QTableWidgetItem(repr(float(strain))))
            table.setItem(r, 1, QTableWidgetItem(repr(float(stress))))

    # ── populate and read ───────────────────────────────────────────
    def _populate_specific(self, material: Any) -> None:
        for name, widget in self.widgets.items():
            value = getattr(material, name)
            if isinstance(widget, QComboBox):
                self._set_combo(widget, value)
            elif isinstance(widget, QListWidget):
                self._set_ids(widget, value)
            elif isinstance(widget, QTableWidget):
                widget.setRowCount(0)
                self._set_points(widget, value)
            elif isinstance(widget, QLineEdit):
                widget.setText(", ".join(f"{v:g}" for v in value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            elif isinstance(widget, FloatField):
                widget.setValue(float(value))

    def _value(self, name: str, widget: QWidget) -> Any:
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QListWidget):
            return [
                widget.item(r).data(Qt.ItemDataRole.UserRole)
                for r in range(widget.count())
                if widget.item(r).checkState() == Qt.CheckState.Checked
            ]
        if isinstance(widget, QTableWidget):
            points = []
            for r in range(widget.rowCount()):
                cells = [widget.item(r, c) for c in (0, 1)]
                texts = [c.text().strip() if c is not None else "" for c in cells]
                if not any(texts):
                    continue
                try:
                    points.append((float(texts[0]), float(texts[1])))
                except ValueError:
                    raise ValueError(f"{name}, row {r + 1}: type two numbers.") from None
            return points
        if isinstance(widget, QLineEdit):
            text = widget.text().replace(";", ",").strip()
            try:
                return [float(t) for t in text.split(",") if t.strip()]
            except ValueError:
                raise ValueError(f"{name}: type numbers separated by commas.") from None
        if isinstance(widget, QSpinBox):
            return widget.value()
        assert isinstance(widget, FloatField)
        return widget.value()

    def _read_specific(self, material_id: int) -> Any:
        values = {name: self._value(name, w) for name, w in self.widgets.items()}
        return self.model(id=material_id, name=self._name_edit.text(), **values)


def form_class(
    model: type[Any], defaults: dict[str, Any] | None = None
) -> type[SignatureMaterialForm]:
    """The form subclass for one material type (``defaults`` fill its required fields)."""
    return type(
        f"{model.__name__}Form",
        (SignatureMaterialForm,),
        {"model": model, "defaults": defaults or {}},
    )
