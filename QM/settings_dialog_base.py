"""Common, schema-driven settings dialogs for QM GUI programs.

Each experiment can define a SETTINGS_SCHEMA dictionary and optionally a SETTINGS_APP/SETTINGS_GROUP.

Schema format (per field):
    {
        "key": {
            "label": "Label:",
            "default": 123,
            "type": int | float | str,
            # optional:
            "widget": "lineedit",  # future extension
            "spacer_after": True,   # inserts a blank QLabel after this field
        },
        ...
    }

This module centralizes:
- widget construction
- loading persisted values from QSettings
- saving on accept()
- typed value retrieval with safe coercion

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Type

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout


@dataclass(frozen=True)
class SettingField:
    label: str
    default: Any
    type: Type
    widget: str = "lineedit"
    spacer_after: bool = False


class SettingsDialogBase(QDialog):
    """Schema-driven settings dialog.

    Subclasses should override:
      - SETTINGS_SCHEMA: dict[str, dict]
      - SETTINGS_APP / SETTINGS_GROUP (optional)
      - WINDOW_TITLE (optional)

    By default, widgets are QLineEdit's.
    """

    SETTINGS_APP = "Diamond"
    SETTINGS_GROUP = "QM"
    WINDOW_TITLE = "Settings"

    # To be overridden by subclasses
    SETTINGS_SCHEMA: Dict[str, Dict[str, Any]] = {}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.WINDOW_TITLE)

        # key -> input widget
        self.settable_values: Dict[str, Any] = {}

        layout = QVBoxLayout()

        for key, field in self._iter_fields():
            layout.addWidget(QLabel(field.label))
            if field.widget == "checkbox" or field.type is bool:
                w = QCheckBox(parent=self)
            else:
                w = QLineEdit(parent=self)
            self.settable_values[key] = w
            layout.addWidget(w)
            if field.spacer_after:
                layout.addWidget(QLabel(""))

        buttons = QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        button_box = QDialogButtonBox(buttons)
        button_box.accepted.connect(self.accept)  # type: ignore
        button_box.rejected.connect(self.reject)  # type: ignore
        layout.addWidget(button_box)

        self.setLayout(layout)

        self.load_settings()

    @classmethod
    def qsettings(cls) -> QSettings:
        return QSettings(cls.SETTINGS_APP, cls.SETTINGS_GROUP)

    # --- schema helpers ---
    @classmethod
    def _field_from_meta(cls, meta: Dict[str, Any]) -> SettingField:
        widget = meta.get("widget")
        if not widget:
            widget = "checkbox" if meta.get("type", str) is bool else "lineedit"
        return SettingField(
            label=str(meta.get("label", "")),
            default=meta.get("default", None),
            type=meta.get("type", str),
            widget=str(widget),
            spacer_after=bool(meta.get("spacer_after", False)),
        )

    @classmethod
    def _iter_fields(cls):
        for key, meta in cls.SETTINGS_SCHEMA.items():
            yield key, cls._field_from_meta(meta)

    # --- coercion / typed access ---
    @classmethod
    def coerce_value(cls, key: str, raw_value: Any) -> Any:
        meta = cls.SETTINGS_SCHEMA[key]
        field = cls._field_from_meta(meta)
        default = field.default
        t = field.type

        if raw_value is None:
            return default

        if t is float:
            try:
                if isinstance(raw_value, str):
                    s = raw_value.strip().replace(",", ".")
                    if s == "":
                        return default
                    return float(s)
                return float(raw_value)
            except (ValueError, TypeError):
                return default

        if t is int:
            try:
                if isinstance(raw_value, str):
                    s = raw_value.strip().replace("_", "")
                    if s == "":
                        return default
                    return int(float(s))  # allow scientific notation
                return int(raw_value)
            except (ValueError, TypeError):
                return default

        if t is str:
            try:
                return str(raw_value)
            except Exception:
                return str(default) if default is not None else ""

        if t is bool:
            if isinstance(raw_value, bool):
                return raw_value
            if isinstance(raw_value, (int, float)):
                return bool(raw_value)
            if isinstance(raw_value, str):
                s = raw_value.strip().lower()
                if s in ("1", "true", "t", "yes", "y", "on"):
                    return True
                if s in ("0", "false", "f", "no", "n", "off", ""):
                    return False
            return bool(raw_value)

        try:
            return t(raw_value)
        except Exception:
            return default

    @classmethod
    def load_value(cls, key: str) -> Any:
        if key not in cls.SETTINGS_SCHEMA:
            return cls.qsettings().value(key, None)
        field = cls._field_from_meta(cls.SETTINGS_SCHEMA[key])
        raw = cls.qsettings().value(key, field.default)
        return cls.coerce_value(key, raw)

    @classmethod
    def get_settings(cls) -> Dict[str, Any]:
        """Typed dict of all schema keys -> coerced values."""
        return cls.get_settings_dict()

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Typed getter for a single key.

        If the key is not part of the schema, returns QSettings value or provided default.
        """
        if key in cls.SETTINGS_SCHEMA:
            return cls.load_value(key)
        return cls.qsettings().value(key, default)

    @classmethod
    def get_settings_dict(cls) -> Dict[str, Any]:
        """Typed dict of all schema keys -> coerced values."""
        out: Dict[str, Any] = {}
        for key, field in cls._iter_fields():
            raw = cls.qsettings().value(key, field.default)
            out[key] = cls.coerce_value(key, raw)
        return out

    # --- instance methods (UI wiring) ---
    def load_settings(self) -> None:
        """Load saved settings and update widgets."""
        qs = self.qsettings()
        for key, field in self._iter_fields():
            raw = qs.value(key, field.default)
            value = self.coerce_value(key, raw)
            widget = self.settable_values[key]
            if isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            else:
                widget.setText(str(value))

    @classmethod
    def set(cls, name, value):
        qs = cls.qsettings()
        qs.setValue(name, value)

    def accept(self) -> None:
        """Save widget contents back to QSettings."""
        qs = self.qsettings()
        for key in self.SETTINGS_SCHEMA.keys():
            widget = self.settable_values[key]
            if isinstance(widget, QCheckBox):
                qs.setValue(key, widget.isChecked())
            else:
                qs.setValue(key, widget.text())
        super().accept()
