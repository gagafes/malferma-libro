"""Compact, cancellable background operations for the GTK application window."""

from __future__ import annotations

from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
import logging
from threading import Lock

from gi.repository import GLib, Gtk, Pango

from .live_i18n import TranslationBindings, localized as _, localized_join
from .tasks import OperationToken, TaskCancelled, error_category
from .books import BookError
from .native_process import native_process_cancellation


LOG = logging.getLogger(__name__)


@dataclass
class _Task:
    identifier: int
    description: str
    token: OperationToken
    future: Future | None = None
    row: object = None
    spinner: object = None
    progress: object = None
    detail: object = None
    cancel_button: object = None
    unsubscribe: list = field(default_factory=list)
    queue_lock: Lock = field(default_factory=Lock)
    ui_queued: bool = False
    cancel_announced: bool = False
    on_cancel: object = None


class TaskMixin:
    def init_tasks(self):
        self._tasks = {}
        self._task_serial = 0
        self._tasks_closed = False
        self._busy_count = 0
        self._task_bindings = TranslationBindings()
        self.operation_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        title = Gtk.Label(xalign=0)
        title.add_css_class("heading")
        self._task_bindings.leading_label(title)
        self._task_bindings.bind(title, label=_("Выполняемые действия"))
        content.append(title)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER,
                                   propagate_natural_height=True, max_content_height=320,
                                   min_content_width=260)
        scroll.set_child(self.operation_rows)
        content.append(scroll)
        self.operation_popover = Gtk.Popover(child=content)
        self.operation_count = Gtk.Label()
        icon = Gtk.Image.new_from_icon_name("view-list-symbolic")
        self.operation_activity = Gtk.Stack()
        self.operation_activity.add_named(icon, "idle")
        self.operation_activity.add_named(self.spinner, "busy")
        button_content = Gtk.Box(spacing=4)
        button_content.append(self.operation_activity)
        button_content.append(self.operation_count)
        self.operation_button = Gtk.MenuButton(child=button_content)
        self.operation_button.set_popover(self.operation_popover)
        self._task_bindings.bind(self.operation_button, tooltip_text=_("Выполняемые действия"))
        self._bind_task_accessible_label(self.operation_button, _("Выполняемые действия"))
        self.utility_controls.append(self.operation_button)
        self._refresh_tasks()

    def refresh_task_translations(self):
        self._task_bindings.refresh(rtl=self.get_direction() == Gtk.TextDirection.RTL)

    def _bind_task_accessible_label(self, widget, text):
        self._task_bindings.bind_value(
            widget, "accessible-label", text,
            lambda item, value: item.update_property([Gtk.AccessibleProperty.LABEL], [value]),
        )

    def _create_task_row(self, task):
        task.row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        heading = Gtk.Box(spacing=8)
        task.spinner = Gtk.Spinner()
        task.spinner.start()
        heading.append(task.spinner)
        title = Gtk.Label(xalign=0, hexpand=True, wrap=True, max_width_chars=32,
                          ellipsize=Pango.EllipsizeMode.END)
        self._task_bindings.leading_label(title)
        self._task_bindings.bind(title, label=task.description)
        heading.append(title)
        task.cancel_button = Gtk.Button(icon_name="process-stop-symbolic")
        self._task_bindings.bind(task.cancel_button, tooltip_text=_("Отменить"))
        self._bind_task_accessible_label(task.cancel_button, _("Отменить"))
        task.cancel_button.connect("clicked", lambda _button: self.cancel_task(task.token))
        heading.append(task.cancel_button)
        task.row.append(heading)
        task.progress = Gtk.ProgressBar(visible=False)
        task.row.append(task.progress)
        task.detail = Gtk.Label(xalign=0, wrap=True, max_width_chars=38)
        task.detail.add_css_class("dim-label")
        self._task_bindings.leading_label(task.detail)
        self._task_bindings.bind(task.detail, label=_("Ожидание данных…"))
        task.row.append(task.detail)
        self.operation_rows.append(task.row)

    def _refresh_tasks(self):
        self._busy_count = sum(not task.token.cancelled for task in self._tasks.values())
        if self._busy_count:
            self.spinner.start()
        else:
            self.spinner.stop()
        if hasattr(self, "operation_activity"):
            self.operation_activity.set_visible_child_name("busy" if self._busy_count else "idle")
        self.operation_count.set_text(str(len(self._tasks)))
        self.operation_button.set_sensitive(bool(self._tasks))
        self.operation_button.set_visible(bool(self._tasks))

    def _update_task_row(self, task):
        if task.token.cancelled:
            task.spinner.stop()
            task.progress.set_visible(False)
            task.cancel_button.set_sensitive(False)
            self._task_bindings.bind(task.detail, label=_("Отмена запрошена"))
            if not task.cancel_announced:
                task.cancel_announced = True
                self.set_status(_("Действие отменено: {action}. Уже выполненные изменения сохраняются.").format(action=task.description))
                if task.on_cancel is not None:
                    try:
                        task.on_cancel()
                    except Exception:
                        LOG.exception("Could not apply cancellation UI state")
        else:
            done, total = task.token.progress_value
            determinate = total is not None and total > 0
            task.progress.set_visible(determinate)
            if determinate:
                task.spinner.stop()
                fraction = max(0, min(1, done / total))
                task.progress.set_fraction(fraction)
                self._task_bindings.bind(task.detail, label=_("Выполнено: {percent}%").format(percent=round(fraction * 100)))
            else:
                task.spinner.start()
                self._task_bindings.bind(task.detail, label=_("Ожидание данных…"))
        self._refresh_tasks()

    def _queue_task_update(self, task):
        if self._tasks_closed:
            return
        with task.queue_lock:
            if task.ui_queued:
                return
            task.ui_queued = True
        def update():
            with task.queue_lock:
                task.ui_queued = False
            if not self._tasks_closed and self._tasks.get(task.identifier) is task:
                self._update_task_row(task)
            return GLib.SOURCE_REMOVE
        GLib.idle_add(update)

    def cancel_task(self, operation):
        token = getattr(operation, "operation_token", operation)
        for task in tuple(self._tasks.values()):
            if task.token is token:
                token.cancel()
                if task.future is not None:
                    task.future.cancel()
                self._update_task_row(task)
                return True
        return False

    def _remove_task(self, task):
        for unsubscribe in task.unsubscribe:
            unsubscribe()
        task.unsubscribe.clear()
        self._tasks.pop(task.identifier, None)
        if task.row is not None:
            task.spinner.stop()
            self.operation_rows.remove(task.row)
        self._refresh_tasks()

    def _show_task_error(self, description, error, retry=None):
        if self._closing or self._tasks_closed:
            return
        category = error_category(error)
        if category == "missing":
            instruction = _("Файл не найден. Выберите книгу снова или проверьте, доступен ли диск.")
        elif category == "permission":
            instruction = _("Нет доступа. Проверьте права на файл или выберите другой каталог.")
        elif category == "network":
            instruction = _("Не удалось получить данные. Проверьте соединение и адрес каталога, затем повторите действие.")
        else:
            instruction = _("Проверьте доступ к файлу или каталогу и повторите действие.")
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.NONE)
        self._task_bindings.bind(dialog, text=description,
                                 secondary_text=localized_join("\n\n", (str(error), instruction)))
        self._task_bindings.bind(dialog.add_button(str(_("Закрыть")), Gtk.ResponseType.CLOSE), label=_("Закрыть"))
        if retry is not None:
            self._task_bindings.bind(dialog.add_button(str(_("Повторить")), Gtk.ResponseType.APPLY), label=_("Повторить"))
        choose_file = (category in {"missing", "permission"} or isinstance(error, BookError)) and callable(getattr(self, "choose_files", None))
        if choose_file:
            self._task_bindings.bind(dialog.add_button(str(_("Выбрать книгу…")), Gtk.ResponseType.ACCEPT), label=_("Выбрать книгу…"))
        def response(item, answer):
            item.destroy()
            if self._closing or self._tasks_closed:
                return
            if answer == Gtk.ResponseType.APPLY and retry is not None:
                retry()
            elif answer == Gtk.ResponseType.ACCEPT and choose_file:
                self.choose_files()
        dialog.connect("response", response)
        self.set_status(description)
        dialog.present()

    def run_task(self, operation, done, description, relevant=None, on_stale=None, on_error=None,
                 *, retry=None, token=None, on_cancel=None):
        token = token if token is not None else OperationToken()
        self._task_serial += 1
        task = _Task(self._task_serial, description, token, on_cancel=on_cancel)
        if self._tasks_closed or self._closing:
            token.cancel()
            future = Future()
            future.operation_token = token
            future.cancel()
            return future
        self._tasks[task.identifier] = task
        self._create_task_row(task)
        task.unsubscribe.append(token.add_progress_callback(lambda *_progress: self._queue_task_update(task)))
        task.unsubscribe.append(token.add_cancel_callback(lambda: self._queue_task_update(task)))
        self._refresh_tasks()
        self.set_status(description, announce=False)
        def work():
            token.check()
            with native_process_cancellation(token):
                return operation()
        try:
            future = self.executor.submit(work)
        except Exception as error:
            future = Future()
            future.set_exception(error)
        task.future = future
        future.operation_token = token

        def finish(completed):
            def deliver():
                result, error = None, None
                try:
                    result = completed.result()
                except Exception as failure:
                    error = failure
                if self._tasks_closed or self._closing:
                    return GLib.SOURCE_REMOVE
                cancelled = token.cancelled or isinstance(error, (TaskCancelled, CancelledError))
                if cancelled:
                    token.cancel()
                    self._update_task_row(task)
                self._remove_task(task)
                try:
                    stale = relevant is not None and not relevant()
                    if cancelled or stale:
                        # Imports can commit before cancellation is observed.
                        # Refresh those changes, without opening a stale book.
                        if on_stale is not None:
                            on_stale()
                    elif error is not None:
                        if on_error is not None:
                            on_error(error)
                        self._show_task_error(description, error, retry)
                    else:
                        done(result)
                except Exception as failure:
                    LOG.exception("Could not apply background-operation result")
                    self._show_task_error(description, failure, retry)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(deliver)

        future.add_done_callback(finish)
        return future

    def close_tasks(self):
        self._tasks_closed = True
        for task in tuple(self._tasks.values()):
            for unsubscribe in task.unsubscribe:
                unsubscribe()
            task.unsubscribe.clear()
            task.token.cancel()
            if task.future is not None:
                task.future.cancel()
        self._tasks.clear()
        self._busy_count = 0
        self.spinner.stop()
        self.operation_popover.popdown()
        self.operation_button.set_sensitive(False)
