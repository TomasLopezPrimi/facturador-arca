"""Selector de fechas reutilizable por los formularios."""

import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk


MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")


class CalendarioFecha(tk.Toplevel):
    def __init__(self, padre, variable, boton, titulo="Elegir fecha", permitir_futuras=False):
        super().__init__(padre)
        self.title(titulo)
        self.resizable(False, False)
        self.transient(padre)
        self.variable = variable
        self.permitir_futuras = permitir_futuras
        try:
            inicial = datetime.strptime(variable.get(), "%d/%m/%Y").date()
        except ValueError:
            inicial = date.today()
        self.mes = tk.StringVar(value=MESES[inicial.month - 1])
        self.anio = tk.StringVar(value=str(inicial.year))
        controles = ttk.Frame(self, padding=12)
        controles.pack(fill="x")
        mes = ttk.Combobox(controles, textvariable=self.mes, values=MESES, state="readonly", width=16)
        mes.pack(side="left")
        mes.bind("<<ComboboxSelected>>", lambda _evento: self._dibujar())
        self.anio_maximo = max(inicial.year, date.today().year + 10) if permitir_futuras else date.today().year
        anio = ttk.Spinbox(controles, textvariable=self.anio, from_=1900, to=self.anio_maximo, width=7, command=self._dibujar)
        anio.pack(side="left", padx=8)
        anio.bind("<Return>", lambda _evento: self._dibujar())
        anio.bind("<FocusOut>", lambda _evento: self._dibujar())
        self.dias = ttk.Frame(self, padding=(12, 0, 12, 8))
        self.dias.pack()
        ttk.Button(self, text="Hoy", command=lambda: self._elegir(date.today())).pack(pady=(0, 12))
        self._dibujar()
        self.geometry(f"+{boton.winfo_rootx()}+{boton.winfo_rooty() + boton.winfo_height()}")
        self.grab_set()
        self.focus_set()

    def _dibujar(self):
        for widget in self.dias.winfo_children():
            widget.destroy()
        try:
            anio = int(self.anio.get())
            mes = MESES.index(self.mes.get()) + 1
            if not 1900 <= anio <= self.anio_maximo:
                return
        except (ValueError, TypeError):
            return
        for columna, nombre in enumerate(("Lu", "Ma", "Mi", "Ju", "Vi", "Sa", "Do")):
            ttk.Label(self.dias, text=nombre, anchor="center", width=4).grid(row=0, column=columna, padx=2, pady=2)
        for fila, semana in enumerate(calendar.monthcalendar(anio, mes), 1):
            for columna, dia in enumerate(semana):
                if not dia:
                    continue
                fecha = date(anio, mes, dia)
                boton = ttk.Button(self.dias, text=str(dia), width=4, command=lambda valor=fecha: self._elegir(valor))
                boton.grid(row=fila, column=columna, padx=2, pady=2)
                if fecha > date.today() and not self.permitir_futuras:
                    boton.configure(state="disabled")

    def _elegir(self, fecha):
        self.variable.set(fecha.strftime("%d/%m/%Y"))
        self.destroy()
