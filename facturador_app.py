"""Interfaz de escritorio de facturación personal con ARCA."""

import os
import threading
import tkinter as tk
import calendar
import webbrowser
import uuid
from datetime import date, datetime
from tkinter import messagebox, ttk
import msvcrt

from facturador_core import (
    BASE, CONDICIONES_IVA, cargar_config,
    guardar_json_atomico, CONFIG_PATH, estado_servicios, obtener_tickets,
    preparar, recuperar_pendiente, consultar_padron_para_interfaz, validar_cuit,
    solicitar, validar_formulario, TIPO_SERVICIO, cargar_receptores,
    guardar_receptores, CONDICIONES_VENTA,
)
from emitir_factura import ErrorConstanciaPadron
from facturador_detalle import UNIDADES_MEDIDA, normalizar_items, total_items
from facturador_pdf import numero_local


AZUL = "#183153"
FONDO = "#f4f6f9"
AMBIENTES = {"Homologación": "testing", "Producción": "produccion"}
CONDICIONES_EMISOR = ("Monotributista", "Exento en IVA")
INGRESOS_BRUTOS = ("Inscripto local", "Convenio Multilateral", "Régimen simplificado", "Exento", "No contribuyente")
INGRESOS_BRUTOS_CON_NUMERO = INGRESOS_BRUTOS[:3]
MESES = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
RECEPTOR_MANUAL = "— Carga manual / nuevo —"


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


class Facturador(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Facturador ARCA · comprobantes C")
        self.geometry("850x800")
        self.minsize(740, 735)
        self.configure(bg=FONDO)
        self._trabajando = False
        self._config = cargar_config()
        self._campos = {}
        self._aplicando_mes_periodo = False
        self._receptores_error = None
        try:
            self._receptores = cargar_receptores()
        except (OSError, ValueError) as error:
            self._receptores = []
            self._receptores_error = error
        self._receptor_actual_id = None
        self._construir()
        self._actualizar_tipo()
        self._actualizar_documento()
        if self._receptores_error:
            self.after(250, lambda: messagebox.showerror(
                "Receptores guardados",
                f"No se pudo leer la libreta local de receptores:\n{self._receptores_error}",
                parent=self,
            ))
        self.after(200, self._aviso_inicial)

    def _construir(self):
        estilo = ttk.Style(self)
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 19, "bold"), foreground=AZUL, background=FONDO)
        estilo.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#526477", background=FONDO)
        estilo.configure("TLabel", font=("Segoe UI", 10))
        estilo.configure("TButton", font=("Segoe UI", 10), padding=7)
        estilo.configure("Emitir.TButton", font=("Segoe UI", 10, "bold"), padding=10)

        cabecera = tk.Frame(self, bg=FONDO)
        cabecera.pack(fill="x", padx=26, pady=(22, 8))
        ttk.Label(cabecera, text="Facturador ARCA", style="Titulo.TLabel").pack(anchor="w")
        self._emisor_cuit_texto = tk.StringVar(value=f"Emisor CUIT {self._config.get('cuit_emisor') or '(sin configurar)'} · Factura C y nota de crédito C")
        ttk.Label(cabecera, textvariable=self._emisor_cuit_texto, style="Sub.TLabel").pack(anchor="w")

        cuaderno = ttk.Notebook(self)
        cuaderno.pack(fill="both", expand=True, padx=24, pady=(8, 16))
        emision = ttk.Frame(cuaderno)
        receptores = ttk.Frame(cuaderno, padding=20)
        configuracion = ttk.Frame(cuaderno, padding=20)
        servicios = ttk.Frame(cuaderno, padding=20)
        cuaderno.add(emision, text="  Emitir comprobante  ")
        cuaderno.add(receptores, text="  Receptores guardados  ")
        cuaderno.add(configuracion, text="  Configuración  ")
        cuaderno.add(servicios, text="  Certificados y tickets  ")
        self.cuaderno = cuaderno
        self.tab_emision = emision
        self._botones_padron = []
        self._construir_emision(emision)
        self._construir_receptores(receptores)
        self._construir_config(configuracion)
        self._construir_servicios(servicios)

    def _fila(self, padre, fila, etiqueta, variable, *, valores=None, ancho=42):
        ttk.Label(padre, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=7, padx=(0, 14))
        if valores is None:
            widget = ttk.Entry(padre, textvariable=variable, width=ancho)
        else:
            widget = ttk.Combobox(padre, textvariable=variable, values=valores, width=ancho - 3, state="readonly")
        widget.grid(row=fila, column=1, sticky="ew", pady=7)
        padre.columnconfigure(1, weight=1)
        return widget

    def _fila_domicilio(self, padre, fila, variable, rol):
        ttk.Label(padre, text="Domicilio comercial").grid(row=fila, column=0, sticky="w", pady=7, padx=(0, 14))
        contenedor = ttk.Frame(padre)
        contenedor.grid(row=fila, column=1, sticky="ew", pady=7)
        contenedor.columnconfigure(0, weight=1)
        entrada = ttk.Entry(contenedor, textvariable=variable)
        entrada.grid(row=0, column=0, sticky="ew")
        boton = ttk.Button(contenedor, text="Ver fiscal en ARCA", command=lambda: self._consultar_padron(rol))
        boton.grid(row=0, column=1, padx=(9, 0))
        self._botones_padron.append(boton)
        padre.columnconfigure(1, weight=1)
        return boton

    def _construir_emision(self, padre):
        padre.rowconfigure(0, weight=1)
        padre.columnconfigure(0, weight=1)
        canvas = tk.Canvas(padre, highlightthickness=0, borderwidth=0)
        barra = ttk.Scrollbar(padre, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=barra.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        contenido = ttk.Frame(canvas, padding=20)
        ventana = canvas.create_window((0, 0), window=contenido, anchor="nw")
        contenido.bind(
            "<Configure>",
            lambda _evento: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda evento: canvas.itemconfigure(ventana, width=evento.width),
        )
        canvas.bind("<Enter>", lambda _evento: canvas.bind_all(
            "<MouseWheel>", lambda evento: canvas.yview_scroll(-int(evento.delta / 120), "units")
        ))
        canvas.bind("<Leave>", lambda _evento: canvas.unbind_all("<MouseWheel>"))
        padre = contenido

        vars_ = {
            "ambiente": tk.StringVar(value="Homologación"),
            "tipo": tk.StringVar(value="Factura C"),
            "concepto": tk.StringVar(value="Servicios"),
            "condicion_venta": tk.StringVar(value="Transferencia Bancaria"),
            "tipo_servicio": tk.StringVar(value=TIPO_SERVICIO),
            "receptor_guardado": tk.StringVar(value=RECEPTOR_MANUAL),
            "fecha": tk.StringVar(value=date.today().strftime("%d/%m/%Y")),
            "servicio_desde": tk.StringVar(value=date.today().strftime("%d/%m/%Y")),
            "servicio_hasta": tk.StringVar(value=date.today().strftime("%d/%m/%Y")),
            "vencimiento_pago": tk.StringVar(value=date.today().strftime("%d/%m/%Y")),
            "mes_periodo": tk.StringVar(value="Seleccionar mes completo…"),
            "documento_tipo": tk.StringVar(value="CUIT"),
            "receptor": tk.StringVar(),
            "nombre_receptor": tk.StringVar(),
            "domicilio_receptor": tk.StringVar(),
            "iva": tk.StringVar(value="Responsable inscripto"),
            "descripcion": tk.StringVar(),
            "importe": tk.StringVar(),
            "original_punto": tk.StringVar(),
            "original_numero": tk.StringVar(),
        }
        self._campos = vars_
        self._meses_periodo = self._opciones_meses_periodo()
        vars_["servicio_desde"].trace_add("write", self._periodo_manual_cambiado)
        vars_["servicio_hasta"].trace_add("write", self._periodo_manual_cambiado)
        aviso = ttk.Label(padre, text="Producción solicita un CAE real. Homologación sirve para probar sin validez fiscal.", foreground="#8a4b13", wraplength=760)
        aviso.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 13))
        self._fila(padre, 1, "Ambiente", vars_["ambiente"], valores=tuple(AMBIENTES))
        tipo = self._fila(padre, 2, "Comprobante", vars_["tipo"], valores=("Factura C", "Nota de crédito C"))
        tipo.bind("<<ComboboxSelected>>", lambda _evento: self._actualizar_tipo())
        concepto = self._fila(padre, 3, "Operación", vars_["concepto"], valores=("Servicios", "Productos"))
        concepto.bind("<<ComboboxSelected>>", lambda _evento: self._actualizar_concepto())
        self._fila(padre, 4, "Condición de venta", vars_["condicion_venta"], valores=CONDICIONES_VENTA)
        self.etiqueta_tipo_servicio = ttk.Label(padre, text="Tipo de servicio")
        self.etiqueta_tipo_servicio.grid(row=5, column=0, sticky="w", pady=7, padx=(0, 14))
        self.selector_tipo_servicio = ttk.Combobox(
            padre,
            textvariable=vars_["tipo_servicio"],
            values=(TIPO_SERVICIO,),
            state="readonly",
        )
        self.selector_tipo_servicio.grid(row=5, column=1, sticky="ew", pady=7)
        padre.columnconfigure(1, weight=1)
        self._fila_fecha(padre, 6, "Fecha del comprobante", vars_["fecha"])
        self.marco_periodo = ttk.LabelFrame(padre, text="Período del servicio", padding=(10, 3))
        self.marco_periodo.grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        self._fila(
            self.marco_periodo, 0, "Mes completo (últimos 6)", vars_["mes_periodo"],
            valores=("Seleccionar mes completo…", *self._meses_periodo),
        ).bind("<<ComboboxSelected>>", self._seleccionar_mes_periodo)
        self._fila_fecha(self.marco_periodo, 1, "Desde", vars_["servicio_desde"])
        self._fila_fecha(self.marco_periodo, 2, "Hasta", vars_["servicio_hasta"])
        self._fila_fecha(self.marco_periodo, 3, "Vencimiento para el pago", vars_["vencimiento_pago"], permitir_futuras=True)
        self.selector_receptor_guardado = self._fila(
            padre, 8, "Receptor guardado", vars_["receptor_guardado"],
            valores=(RECEPTOR_MANUAL,),
        )
        self.selector_receptor_guardado.bind(
            "<<ComboboxSelected>>", self._seleccionar_receptor_guardado
        )
        self.documento_tipo_selector = self._fila(
            padre, 9, "Documento del receptor", vars_["documento_tipo"],
            valores=("CUIT", "DNI", "Sin documento"),
        )
        documento = self.documento_tipo_selector
        documento.bind("<<ComboboxSelected>>", lambda _evento: self._actualizar_documento())
        self.entrada_documento = self._fila(padre, 10, "Número de documento", vars_["receptor"])
        self._fila(padre, 11, "Nombre o razón social", vars_["nombre_receptor"])
        self.boton_padron_receptor = self._fila_domicilio(padre, 12, vars_["domicilio_receptor"], "receptor")
        ttk.Button(
            padre,
            text="Guardar receptor",
            command=self._guardar_receptor_desde_emision,
        ).grid(row=13, column=1, sticky="w", pady=(0, 5))
        self.selector_iva = self._fila(padre, 14, "IVA del receptor", vars_["iva"], valores=tuple(CONDICIONES_IVA))
        self._construir_detalle(padre, 15)
        self._fila(padre, 16, "Importe total ($)", vars_["importe"]).configure(state="readonly")

        self.marco_original = ttk.LabelFrame(padre, text="Factura C original", padding=12)
        self.marco_original.grid(row=17, column=0, columnspan=2, sticky="ew", pady=(10, 3))
        self._fila(self.marco_original, 0, "Punto de venta", vars_["original_punto"], ancho=18)
        self._fila(self.marco_original, 1, "Número", vars_["original_numero"], ancho=18)

        botones = ttk.Frame(padre)
        botones.grid(row=18, column=0, columnspan=2, sticky="ew", pady=(22, 12))
        self.boton_emitir = ttk.Button(botones, text="Revisar y emitir", style="Emitir.TButton", command=self._emitir)
        self.boton_emitir.pack(side="left")
        self.boton_recuperar = ttk.Button(botones, text="Recuperar solicitud pendiente", command=self._recuperar)
        self.boton_recuperar.pack(side="left", padx=12)
        ttk.Button(botones, text="Abrir comprobantes", command=self._abrir_carpeta).pack(side="right")
        self.estado = tk.StringVar(value="Listo para cargar un comprobante.")
        ttk.Label(padre, textvariable=self.estado, foreground="#526477", wraplength=730).grid(row=19, column=0, columnspan=2, sticky="w")
        self._actualizar_concepto()
        self._actualizar_selector_receptores()

    def _fila_fecha(self, padre, fila, etiqueta, variable, permitir_futuras=False):
        ttk.Label(padre, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=4, padx=(0, 14))
        contenedor = ttk.Frame(padre)
        contenedor.grid(row=fila, column=1, sticky="ew", pady=4)
        ttk.Entry(contenedor, textvariable=variable, width=18).pack(side="left")
        boton = ttk.Button(contenedor, text="Elegir", command=lambda: CalendarioFecha(
            self, variable, boton, etiqueta, permitir_futuras=permitir_futuras))
        boton.pack(side="left", padx=8)
        padre.columnconfigure(1, weight=1)
        return contenedor

    def _construir_detalle(self, padre, fila):
        self._items = []
        marco = ttk.LabelFrame(padre, text="Productos / servicios", padding=10)
        marco.grid(row=fila, column=0, columnspan=2, sticky="ew", pady=8)
        marco.columnconfigure(0, weight=1)
        columnas = ("descripcion", "cantidad", "unidad", "precio", "importe")
        self.tabla_items = ttk.Treeview(marco, columns=columnas, show="headings", height=5, selectmode="browse")
        for columna, titulo, ancho in zip(columnas, ("Descripción", "Cantidad", "Unidad", "Precio unit.", "Importe"), (240, 75, 80, 105, 105)):
            self.tabla_items.heading(columna, text=titulo)
            self.tabla_items.column(columna, width=ancho, minwidth=55, anchor="w" if columna in ("descripcion", "unidad") else "e")
        self.tabla_items.grid(row=0, column=0, sticky="ew")
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.tabla_items.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.tabla_items.configure(yscrollcommand=barra.set)
        self.tabla_items.bind("<Double-1>", lambda _evento: self._editar_item())
        botones = ttk.Frame(marco)
        botones.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(botones, text="Agregar renglón", command=lambda: self._editar_item(nuevo=True)).pack(side="left")
        ttk.Button(botones, text="Editar", command=self._editar_item).pack(side="left", padx=6)
        ttk.Button(botones, text="Quitar", command=self._quitar_item).pack(side="left")
        self._actualizar_detalle()

    def _actualizar_detalle(self):
        self.tabla_items.delete(*self.tabla_items.get_children())
        for indice, item in enumerate(self._items):
            descripcion = item["descripcion"].replace("\n", " ")
            self.tabla_items.insert("", "end", iid=str(indice), values=(
                descripcion, str(item["cantidad"]).replace(".", ","), item["unidad"],
                numero_local(item["precio_unitario"]), numero_local(item["importe"])))
        self._campos["importe"].set(numero_local(total_items(self._items)))

    def _quitar_item(self):
        seleccion = self.tabla_items.selection()
        if self._trabajando or not seleccion:
            return
        del self._items[int(seleccion[0])]
        self._actualizar_detalle()

    def _editar_item(self, nuevo=False):
        if self._trabajando:
            return
        seleccion = self.tabla_items.selection()
        if not nuevo and not seleccion:
            return
        indice = None if nuevo else int(seleccion[0])
        item = {} if nuevo else self._items[indice]
        ventana = tk.Toplevel(self)
        ventana.title("Agregar renglón" if nuevo else "Editar renglón")
        ventana.transient(self)
        marco = ttk.Frame(ventana, padding=16)
        marco.pack(fill="both", expand=True)
        unidad = "servicio" if self._campos["concepto"].get() == "Servicios" else "unidad"
        variables = {clave: tk.StringVar(value=item.get(clave, defecto)) for clave, defecto in (
            ("codigo", ""), ("cantidad", "1"), ("unidad", unidad), ("precio_unitario", ""))}
        self._fila(marco, 0, "Código (opcional)", variables["codigo"])
        ttk.Label(marco, text="Descripción").grid(row=1, column=0, sticky="nw", pady=7)
        descripcion = tk.Text(marco, width=58, height=7, wrap="word", font=("Segoe UI", 10))
        descripcion.grid(row=1, column=1, sticky="nsew", pady=7)
        descripcion.insert("1.0", item.get("descripcion", ""))
        self._fila(marco, 2, "Cantidad", variables["cantidad"])
        self._fila(marco, 3, "Unidad de medida", variables["unidad"], valores=UNIDADES_MEDIDA)
        self._fila(marco, 4, "Precio unitario ($)", variables["precio_unitario"])
        importe = tk.StringVar(value="—")
        ttk.Label(marco, text="Importe del renglón").grid(row=5, column=0, sticky="w", pady=7)
        ttk.Label(marco, textvariable=importe).grid(row=5, column=1, sticky="w", pady=7)

        def datos_editor():
            return {**{clave: variable.get() for clave, variable in variables.items()},
                    "descripcion": descripcion.get("1.0", "end-1c")}

        def recalcular(*_args):
            try:
                normalizado = normalizar_items([{**datos_editor(), "descripcion": "Vista previa"}])[0]
                importe.set(f"$ {numero_local(normalizado['importe'])}")
            except ValueError:
                importe.set("—")

        def guardar():
            try:
                normalizado = normalizar_items([datos_editor()])[0]
                nuevos = [dict(renglon) for renglon in self._items]
                if indice is None:
                    nuevos.append(normalizado)
                else:
                    nuevos[indice] = normalizado
                self._items = normalizar_items(nuevos)
            except ValueError as error:
                messagebox.showerror("Detalle", str(error), parent=ventana)
                return
            self._actualizar_detalle()
            ventana.destroy()

        for variable in variables.values():
            variable.trace_add("write", recalcular)
        recalcular()
        botones = ttk.Frame(marco)
        botones.grid(row=6, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(botones, text="Cancelar", command=ventana.destroy).pack(side="left", padx=6)
        ttk.Button(botones, text="Guardar renglón", command=guardar).pack(side="left")
        ventana.grab_set()
        descripcion.focus_set()
        self.wait_window(ventana)

    @staticmethod
    def _opciones_meses_periodo():
        hoy = date.today()
        opciones = []
        for desplazamiento in range(6):
            indice_mes = hoy.year * 12 + hoy.month - 1 - desplazamiento
            anio, indice = divmod(indice_mes, 12)
            opciones.append(f"{MESES[indice]} {anio}")
        return tuple(opciones)

    def _seleccionar_mes_periodo(self, _evento=None):
        seleccion = self._campos["mes_periodo"].get()
        if seleccion not in self._meses_periodo:
            return
        nombre_mes, anio_texto = seleccion.rsplit(" ", 1)
        mes = MESES.index(nombre_mes) + 1
        anio = int(anio_texto)
        ultimo_dia = calendar.monthrange(anio, mes)[1]
        self._aplicando_mes_periodo = True
        self._campos["servicio_desde"].set(date(anio, mes, 1).strftime("%d/%m/%Y"))
        self._campos["servicio_hasta"].set(date(anio, mes, ultimo_dia).strftime("%d/%m/%Y"))
        self._aplicando_mes_periodo = False

    def _periodo_manual_cambiado(self, *_args):
        if not self._aplicando_mes_periodo:
            self._campos["mes_periodo"].set("Seleccionar mes completo…")

    def _construir_servicios(self, padre):
        ttk.Label(padre, text="Revisá los certificados y la vigencia de los tickets WSAA guardados. No se muestran los tokens ni las claves.", wraplength=740).pack(anchor="w", pady=(0, 16))
        self._estado_servicios = {}
        self._botones_servicios = []
        for ambiente, titulo in (("testing", "Testing / homologación"), ("produccion", "Producción")):
            marco = ttk.LabelFrame(padre, text=titulo, padding=15)
            marco.pack(fill="x", pady=8)
            variable = tk.StringVar(value=estado_servicios(ambiente))
            self._estado_servicios[ambiente] = variable
            ttk.Label(marco, textvariable=variable, justify="left", wraplength=680).pack(anchor="w")
            botones = ttk.Frame(marco)
            botones.pack(anchor="w", pady=(12, 0))
            ttk.Button(botones, text="Revisar estado", command=lambda a=ambiente: self._revisar_servicios(a)).pack(side="left")
            boton = ttk.Button(botones, text="Obtener o renovar tickets", command=lambda a=ambiente: self._obtener_tickets(a))
            boton.pack(side="left", padx=10)
            self._botones_servicios.append(boton)
        ttk.Label(padre, text="Sin credenciales de producción, podés verificar el CUIT en la consulta pública de ARCA. Requiere completar un código de seguridad.", wraplength=710).pack(anchor="w", pady=(22, 6))
        ttk.Button(padre, text="Abrir constancia pública de ARCA", command=lambda: webbrowser.open("https://seti.arca.gob.ar/padron-puc-constancia-internet/jsp/Constancia.jsp")).pack(anchor="w")

    def _construir_receptores(self, padre):
        descripcion = (
            "Guardá receptores para seleccionarlos al emitir. La libreta queda en esta computadora. "
            "Para agregar o actualizar uno, completá sus datos en Emitir comprobante y elegí Guardar receptor."
        )
        ttk.Label(padre, text=descripcion, wraplength=740).pack(anchor="w", pady=(0, 14))
        contenedor_tabla = ttk.Frame(padre)
        contenedor_tabla.pack(fill="both", expand=True)
        self.tabla_receptores = ttk.Treeview(
            contenedor_tabla,
            columns=("nombre", "documento", "iva", "domicilio"),
            show="headings",
            selectmode="browse",
            height=14,
        )
        barra = ttk.Scrollbar(contenedor_tabla, orient="vertical", command=self.tabla_receptores.yview)
        self.tabla_receptores.configure(yscrollcommand=barra.set)
        self.tabla_receptores.heading("nombre", text="Nombre o razón social")
        self.tabla_receptores.heading("documento", text="Documento")
        self.tabla_receptores.heading("iva", text="Condición IVA")
        self.tabla_receptores.heading("domicilio", text="Domicilio comercial")
        self.tabla_receptores.column("nombre", width=180, minwidth=125)
        self.tabla_receptores.column("documento", width=125, minwidth=90)
        self.tabla_receptores.column("iva", width=140, minwidth=110)
        self.tabla_receptores.column("domicilio", width=230, minwidth=170)
        self.tabla_receptores.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.tabla_receptores.bind(
            "<Double-1>", lambda _evento: self._usar_receptor_seleccionado()
        )
        botones = ttk.Frame(padre)
        botones.pack(fill="x", pady=(12, 0))
        ttk.Button(
            botones,
            text="Usar en comprobante",
            command=self._usar_receptor_seleccionado,
        ).pack(side="left")
        ttk.Button(
            botones,
            text="Eliminar de la libreta",
            command=self._eliminar_receptor_seleccionado,
        ).pack(side="left", padx=10)
        self.estado_receptores = tk.StringVar()
        ttk.Label(padre, textvariable=self.estado_receptores, foreground="#526477").pack(anchor="w", pady=(10, 0))
        self._actualizar_lista_receptores()

    def _etiqueta_receptor(self, receptor):
        documento = str(receptor.get("documento", "")).strip()
        documento_tipo = str(receptor.get("documento_tipo", ""))
        texto_documento = f"{documento_tipo} {documento}" if documento else "Sin documento"
        nombre = str(receptor.get("nombre", "")).strip()
        return f"{nombre} · {texto_documento}"

    def _clave_receptor(self, receptor):
        tipo = str(receptor.get("documento_tipo", ""))
        documento = "".join(caracter for caracter in str(receptor.get("documento", "")) if caracter.isdigit())
        if documento:
            return tipo, documento, ""
        return tipo, "", str(receptor.get("nombre", "")).strip().casefold()

    def _actualizar_selector_receptores(self):
        opciones = [RECEPTOR_MANUAL]
        self._receptor_id_por_etiqueta = {}
        receptores = sorted(self._receptores, key=lambda receptor: str(receptor.get("nombre", "")).casefold())
        for receptor in receptores:
            etiqueta = self._etiqueta_receptor(receptor)
            if etiqueta in self._receptor_id_por_etiqueta:
                etiqueta = f"{etiqueta} · {str(receptor['id'])[:6]}"
            self._receptor_id_por_etiqueta[etiqueta] = receptor["id"]
            opciones.append(etiqueta)
        self.selector_receptor_guardado.configure(values=opciones)
        etiqueta_actual = next(
            (etiqueta for etiqueta, receptor_id in self._receptor_id_por_etiqueta.items()
             if receptor_id == self._receptor_actual_id),
            RECEPTOR_MANUAL,
        )
        self._campos["receptor_guardado"].set(etiqueta_actual)

    def _actualizar_lista_receptores(self):
        if not hasattr(self, "tabla_receptores"):
            return
        for elemento in self.tabla_receptores.get_children():
            self.tabla_receptores.delete(elemento)
        for receptor in sorted(self._receptores, key=lambda registro: str(registro.get("nombre", "")).casefold()):
            documento = str(receptor.get("documento", "")).strip()
            tipo = str(receptor.get("documento_tipo", ""))
            documento_visible = f"{tipo} {documento}" if documento else "Sin documento"
            self.tabla_receptores.insert(
                "",
                "end",
                iid=str(receptor["id"]),
                values=(
                    str(receptor.get("nombre", "")),
                    documento_visible,
                    str(receptor.get("iva", "")),
                    str(receptor.get("domicilio", "")),
                ),
            )
        if self._receptores_error:
            self.estado_receptores.set("No se pudo leer receptores.json; la libreta está en modo de solo lectura.")
        elif self._receptores:
            self.estado_receptores.set(f"{len(self._receptores)} receptor(es) guardado(s).")
        else:
            self.estado_receptores.set("Todavía no hay receptores guardados.")

    def _seleccionar_receptor_guardado(self, _evento=None):
        receptor_id = self._receptor_id_por_etiqueta.get(
            self._campos["receptor_guardado"].get()
        )
        self._receptor_actual_id = receptor_id
        if receptor_id:
            self._cargar_receptor_id(receptor_id, ir_a_emision=False)

    def _cargar_receptor_id(self, receptor_id, *, ir_a_emision=True):
        receptor = next(
            (registro for registro in self._receptores if registro["id"] == receptor_id),
            None,
        )
        if not receptor:
            messagebox.showerror("Receptores", "Ese receptor ya no está en la libreta.", parent=self)
            return
        self._receptor_actual_id = receptor_id
        self._campos["documento_tipo"].set(receptor["documento_tipo"])
        self._campos["receptor"].set(receptor["documento"])
        self._campos["nombre_receptor"].set(receptor["nombre"])
        self._campos["domicilio_receptor"].set(receptor["domicilio"])
        self._campos["iva"].set(receptor["iva"])
        self._actualizar_documento()
        self._actualizar_selector_receptores()
        if ir_a_emision:
            self.cuaderno.select(self.tab_emision)
        self.estado.set(f"Receptor cargado: {receptor['nombre']}.")

    def _usar_receptor_seleccionado(self):
        seleccion = self.tabla_receptores.selection()
        if not seleccion:
            messagebox.showinfo("Receptores guardados", "Seleccioná un receptor de la lista.", parent=self)
            return
        self._cargar_receptor_id(seleccion[0])

    def _guardar_receptor_desde_emision(self):
        if self._receptores_error:
            messagebox.showerror(
                "Receptores guardados",
                "No se puede guardar porque la libreta local no se pudo leer.",
                parent=self,
            )
            return

        tipo = self._campos["documento_tipo"].get()
        documento = self._campos["receptor"].get().strip()
        nombre = self._campos["nombre_receptor"].get().strip()
        domicilio = self._campos["domicilio_receptor"].get().strip()
        iva = self._campos["iva"].get()
        if not nombre:
            messagebox.showerror("Guardar receptor", "Ingresá el nombre o razón social.", parent=self)
            return
        if tipo == "CUIT":
            try:
                documento = validar_cuit(documento)
            except ValueError as error:
                messagebox.showerror("Guardar receptor", str(error), parent=self)
                return
            if not domicilio:
                messagebox.showerror("Guardar receptor", "Ingresá el domicilio comercial.", parent=self)
                return
            if iva not in CONDICIONES_IVA:
                messagebox.showerror("Guardar receptor", "Seleccioná la condición IVA.", parent=self)
                return
        elif tipo == "DNI":
            if not documento.isdigit() or not 7 <= len(documento) <= 8:
                messagebox.showerror("Guardar receptor", "Ingresá un DNI de 7 u 8 dígitos.", parent=self)
                return
            iva = "Consumidor final"
        elif tipo == "Sin documento":
            documento = ""
            iva = "Consumidor final"
        else:
            messagebox.showerror("Guardar receptor", "Seleccioná el tipo de documento.", parent=self)
            return

        receptor = {
            "id": self._receptor_actual_id or uuid.uuid4().hex,
            "documento_tipo": tipo,
            "documento": documento,
            "nombre": nombre,
            "domicilio": domicilio,
            "iva": iva,
        }
        clave = self._clave_receptor(receptor)
        existente = next(
            (registro for registro in self._receptores if self._clave_receptor(registro) == clave),
            None,
        )
        actual = next(
            (registro for registro in self._receptores if registro["id"] == self._receptor_actual_id),
            None,
        )
        if actual and existente and existente["id"] != actual["id"]:
            messagebox.showerror(
                "Guardar receptor",
                "Ya hay otro receptor guardado con ese documento. Seleccionalo para actualizar sus datos.",
                parent=self,
            )
            return
        if not actual and existente:
            if not messagebox.askyesno(
                "Actualizar receptor",
                f"Ya existe {existente['nombre']} en la libreta. ¿Querés actualizar sus datos?",
                parent=self,
            ):
                return
            receptor["id"] = existente["id"]

        if actual:
            receptores = [receptor if registro["id"] == actual["id"] else registro for registro in self._receptores]
        elif existente:
            receptores = [receptor if registro["id"] == existente["id"] else registro for registro in self._receptores]
        else:
            receptores = [*self._receptores, receptor]
        try:
            guardar_receptores(receptores)
        except OSError as error:
            messagebox.showerror("Guardar receptor", f"No se pudo guardar la libreta:\n{error}", parent=self)
            return
        self._receptores = receptores
        self._receptor_actual_id = receptor["id"]
        self._campos["receptor"].set(documento)
        self._actualizar_selector_receptores()
        self._actualizar_lista_receptores()
        self.estado.set(f"Receptor guardado: {nombre}.")

    def _eliminar_receptor_seleccionado(self):
        if self._receptores_error:
            messagebox.showerror(
                "Receptores guardados",
                "No se puede modificar porque la libreta local no se pudo leer.",
                parent=self,
            )
            return
        seleccion = self.tabla_receptores.selection()
        if not seleccion:
            messagebox.showinfo("Receptores guardados", "Seleccioná un receptor de la lista.", parent=self)
            return
        receptor_id = seleccion[0]
        receptor = next(registro for registro in self._receptores if registro["id"] == receptor_id)
        if not messagebox.askyesno(
            "Eliminar receptor",
            f"¿Eliminar a {receptor['nombre']} de la libreta?",
            parent=self,
        ):
            return
        receptores = [registro for registro in self._receptores if registro["id"] != receptor_id]
        try:
            guardar_receptores(receptores)
        except OSError as error:
            messagebox.showerror("Eliminar receptor", f"No se pudo actualizar la libreta:\n{error}", parent=self)
            return
        self._receptores = receptores
        if self._receptor_actual_id == receptor_id:
            self._receptor_actual_id = None
        self._actualizar_selector_receptores()
        self._actualizar_lista_receptores()
        self.estado_receptores.set(f"Se eliminó {receptor['nombre']} de la libreta.")

    def _construir_config(self, padre):
        ttk.Label(padre, text="Datos del emisor que aparecerán en los PDF. El CUIT y punto de venta deben estar habilitados para WSFE.", wraplength=740).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
        self._config_vars = {}
        for indice, (clave, etiqueta) in enumerate((
            ("cuit_emisor", "CUIT emisor"),
            ("punto_venta", "Punto de venta WSFE"),
            ("nombre_emisor", "Nombre o razón social"),
        ), 1):
            variable = tk.StringVar(value=str(self._config.get(clave, "")))
            self._config_vars[clave] = variable
            self._fila(padre, indice, etiqueta, variable)

        domicilio_emisor = tk.StringVar(value=str(self._config.get("domicilio_emisor", "")))
        self._config_vars["domicilio_emisor"] = domicilio_emisor
        self._fila_domicilio(padre, 4, domicilio_emisor, "emisor")

        iva = tk.StringVar(value=str(self._config.get("condicion_iva_emisor", "")))
        self._config_vars["condicion_iva_emisor"] = iva
        self._fila(padre, 5, "Condición frente al IVA", iva, valores=CONDICIONES_EMISOR)

        estado_ibb = self._config.get("ingresos_brutos_estado", "")
        numero_ibb = self._config.get("ingresos_brutos_numero", "")
        if not estado_ibb:
            anterior = str(self._config.get("ingresos_brutos", "")).strip()
            if anterior in INGRESOS_BRUTOS:
                estado_ibb = anterior
            elif anterior:
                estado_ibb = "Inscripto local"
                numero_ibb = anterior
        estado = tk.StringVar(value=estado_ibb)
        numero = tk.StringVar(value=numero_ibb)
        self._config_vars["ingresos_brutos_estado"] = estado
        self._config_vars["ingresos_brutos_numero"] = numero
        selector = self._fila(padre, 6, "Ingresos Brutos", estado, valores=INGRESOS_BRUTOS)
        selector.bind("<<ComboboxSelected>>", lambda _evento: self._actualizar_ingresos_brutos())
        self.entrada_ibb = self._fila(padre, 7, "Número de inscripción IIBB", numero)

        fecha = tk.StringVar(value=str(self._config.get("inicio_actividades", "")))
        self._config_vars["inicio_actividades"] = fecha
        ttk.Label(padre, text="Inicio de actividades").grid(row=8, column=0, sticky="w", pady=7, padx=(0, 14))
        marco_fecha = ttk.Frame(padre)
        marco_fecha.grid(row=8, column=1, sticky="ew", pady=7)
        ttk.Entry(marco_fecha, textvariable=fecha, state="readonly", width=22).pack(side="left")
        boton_fecha = ttk.Button(marco_fecha, text="Elegir fecha")
        boton_fecha.configure(command=lambda: CalendarioFecha(self, fecha, boton_fecha))
        boton_fecha.pack(side="left", padx=9)

        self._actualizar_ingresos_brutos()
        ttk.Button(padre, text="Guardar configuración", command=self._guardar_config).grid(row=9, column=1, sticky="e", pady=18)
        ttk.Label(padre, text="Los certificados deben estar autorizados en ARCA para el CUIT emisor elegido. Se usan desde esta carpeta local y no se copian al PDF.", foreground="#526477", wraplength=730).grid(row=10, column=0, columnspan=2, sticky="w")

    def _actualizar_ingresos_brutos(self):
        estado = self._config_vars["ingresos_brutos_estado"].get()
        self.entrada_ibb.configure(state="normal" if estado in INGRESOS_BRUTOS_CON_NUMERO else "disabled")

    def _guardar_config(self):
        config = {clave: variable.get().strip() for clave, variable in self._config_vars.items()}
        try:
            config["cuit_emisor"] = validar_cuit(config["cuit_emisor"])
        except ValueError as error:
            messagebox.showerror("CUIT emisor", str(error), parent=self)
            return
        try:
            punto = int(config["punto_venta"])
            if not 1 <= punto <= 99998:
                raise ValueError
        except ValueError:
            messagebox.showerror("Punto de venta", "Ingresá un punto de venta válido (1 a 99998).", parent=self)
            return
        if config["condicion_iva_emisor"] and config["condicion_iva_emisor"] not in CONDICIONES_EMISOR:
            messagebox.showerror("Condición IVA", "Seleccioná una condición IVA de la lista.", parent=self)
            return
        estado = config["ingresos_brutos_estado"]
        if estado and estado not in INGRESOS_BRUTOS:
            messagebox.showerror("Ingresos Brutos", "Seleccioná una opción de la lista.", parent=self)
            return
        if estado in INGRESOS_BRUTOS_CON_NUMERO:
            if not config["ingresos_brutos_numero"]:
                messagebox.showerror("Ingresos Brutos", "Ingresá el número de inscripción.", parent=self)
                return
            config["ingresos_brutos"] = f"{estado}: {config['ingresos_brutos_numero']}"
        else:
            config["ingresos_brutos"] = estado
            config["ingresos_brutos_numero"] = ""
        if config["inicio_actividades"]:
            try:
                fecha = datetime.strptime(config["inicio_actividades"], "%d/%m/%Y").date()
                if fecha > date.today():
                    raise ValueError
            except ValueError:
                messagebox.showerror("Inicio de actividades", "Elegí una fecha válida que no sea futura.", parent=self)
                return
        guardar_json_atomico(CONFIG_PATH, config)
        self._config = config
        self._config_vars["cuit_emisor"].set(config["cuit_emisor"])
        self._emisor_cuit_texto.set(f"Emisor CUIT {config['cuit_emisor']} · Factura C y nota de crédito C")
        messagebox.showinfo("Configuración", "Datos guardados en esta computadora.", parent=self)

    def _actualizar_tipo(self):
        if self._campos["tipo"].get() == "Nota de crédito C":
            self.marco_original.grid()
        else:
            self.marco_original.grid_remove()

    def _actualizar_concepto(self):
        if self._campos["concepto"].get() == "Servicios":
            self.marco_periodo.grid()
            self.etiqueta_tipo_servicio.grid()
            self.selector_tipo_servicio.grid()
        else:
            self.marco_periodo.grid_remove()
            self.etiqueta_tipo_servicio.grid_remove()
            self.selector_tipo_servicio.grid_remove()

    def _valor_ambiente(self):
        return AMBIENTES[self._campos["ambiente"].get()]

    def _actualizar_documento(self):
        tipo = self._campos["documento_tipo"].get()
        if tipo == "Sin documento":
            self._campos["receptor"].set("")
            self.entrada_documento.configure(state="disabled")
        else:
            self.entrada_documento.configure(state="normal")
        if tipo == "CUIT":
            self.selector_iva.configure(state="readonly")
        else:
            self._campos["iva"].set("Consumidor final")
            self.selector_iva.configure(state="disabled")
        self.boton_padron_receptor.configure(state="normal" if tipo == "CUIT" and not self._trabajando else "disabled")

    def _consultar_padron(self, rol):
        if self._trabajando:
            return
        ambiente = self._valor_ambiente()
        try:
            cuit_emisor = validar_cuit(self._config_vars["cuit_emisor"].get())
        except ValueError as error:
            messagebox.showerror("CUIT emisor", str(error), parent=self)
            return
        if rol == "emisor":
            cuit = cuit_emisor
        else:
            if self._campos["documento_tipo"].get() != "CUIT":
                messagebox.showinfo("Padrón ARCA", "La consulta de domicilio fiscal está disponible para CUIT.", parent=self)
                return
            try:
                cuit = validar_cuit(self._campos["receptor"].get())
            except ValueError as error:
                messagebox.showerror("CUIT del receptor", str(error), parent=self)
                return
        self._ocupado(True, f"Consultando domicilio fiscal del {rol} en ARCA...")

        def trabajo():
            try:
                perfil = consultar_padron_para_interfaz(cuit, ambiente, cuit_emisor)
                self.after(0, lambda: self._mostrar_padron(rol, cuit, ambiente, perfil))
            except ErrorConstanciaPadron as error:
                if rol == "receptor" and error.permite_carga_manual:
                    self.after(0, lambda error=error: self._padron_receptor_no_disponible(error))
                else:
                    self.after(0, lambda error=error: self._error(error))
            except Exception as error:
                self.after(0, lambda error=error: self._error(error))

        threading.Thread(target=trabajo, daemon=True).start()

    def _padron_receptor_no_disponible(self, error):
        self._ocupado(False, "ARCA no emitió la constancia del receptor.")
        messagebox.showwarning(
            "Constancia no disponible",
            f"{error}\n\n"
            "Podés continuar con este receptor cargando manualmente su nombre, "
            "domicilio comercial y condición frente al IVA. Revisá esos datos: "
            "no fueron verificados por el padrón de ARCA.",
            parent=self,
        )

    def _mostrar_padron(self, rol, cuit, ambiente, perfil):
        self._ocupado(False, "Consulta de padrón completada.")
        if ambiente != self._valor_ambiente():
            return
        if rol == "emisor" and self._config_vars["cuit_emisor"].get().replace("-", "").strip() != cuit:
            return
        if rol == "receptor" and (self._campos["documento_tipo"].get() != "CUIT" or self._campos["receptor"].get().replace("-", "").strip() != cuit):
            return
        fiscal = str(perfil.get("domicilio_fiscal", "")).strip()
        if not fiscal:
            messagebox.showerror("Padrón ARCA", "ARCA no informó un domicilio fiscal para ese CUIT.", parent=self)
            return
        variable = self._config_vars["domicilio_emisor"] if rol == "emisor" else self._campos["domicilio_receptor"]
        actual = variable.get().strip() or "(sin cargar)"
        datos_a_copiar = "nombre y domicilio" if rol == "receptor" else "domicilio"
        advertencia_prueba = "ATENCIÓN: este padrón contiene datos de prueba.\n\n" if "datos de prueba" in perfil.get("fuente", "") else ""
        mensaje = (
            f"{perfil.get('nombre', 'CUIT ' + cuit)}\nCUIT {cuit}\n\n"
            f"Fuente: {perfil.get('fuente', 'Padrón ARCA')}\n\n"
            f"{advertencia_prueba}"
            f"Domicilio fiscal informado por ARCA:\n{fiscal}\n\n"
            f"Domicilio comercial cargado:\n{actual}\n\n"
            "El domicilio fiscal puede ser distinto del comercial. "
            f"¿Confirmás que coinciden y querés copiar {datos_a_copiar} de ARCA al comprobante?"
        )
        if messagebox.askyesno("Confirmar domicilio", mensaje, parent=self):
            variable.set(fiscal)
            if rol == "receptor" and perfil.get("nombre"):
                self._campos["nombre_receptor"].set(perfil["nombre"])
            self.estado.set(f"Domicilio del {rol} copiado del padrón. Guardá Configuración si corresponde.")

    def _revisar_servicios(self, ambiente):
        try:
            self._estado_servicios[ambiente].set(estado_servicios(ambiente))
        except Exception as error:
            self._error(error)

    def _obtener_tickets(self, ambiente):
        if self._trabajando:
            return
        self._ocupado(True, f"Revisando tickets de {ambiente} con ARCA...")

        def trabajo():
            try:
                estado = obtener_tickets(ambiente)
                self.after(0, lambda: self._tickets_listos(ambiente, estado))
            except Exception as error:
                self.after(0, lambda error=error: self._error(error))

        threading.Thread(target=trabajo, daemon=True).start()

    def _tickets_listos(self, ambiente, estado):
        self._estado_servicios[ambiente].set(estado)
        self._ocupado(False, f"Tickets de {ambiente} revisados.")
        messagebox.showinfo("Certificados y tickets", "Estado actualizado. Revisá los vencimientos en esta pestaña.", parent=self)

    def _aviso_inicial(self):
        if not self._config:
            self.cuaderno.select(1)
            messagebox.showinfo("Primer uso", "Completá la Configuración antes de emitir.", parent=self)

    def _ocupado(self, estado, texto):
        self._trabajando = estado
        self.boton_emitir.configure(state="disabled" if estado else "normal")
        self.boton_recuperar.configure(state="disabled" if estado else "normal")
        for boton in self._botones_servicios:
            boton.configure(state="disabled" if estado else "normal")
        for boton in self._botones_padron:
            boton.configure(state="disabled" if estado else "normal")
        if not estado and self._campos["documento_tipo"].get() != "CUIT":
            self.boton_padron_receptor.configure(state="disabled")
        self.estado.set(texto)

    def _error(self, error):
        self._ocupado(False, "No se completó la operación.")
        messagebox.showerror("Facturador ARCA", str(error), parent=self)

    def _emitir(self):
        if self._trabajando:
            return
        try:
            cuit_visible = validar_cuit(self._config_vars["cuit_emisor"].get())
        except ValueError as error:
            self._error(error)
            return
        if cuit_visible != str(self._config.get("cuit_emisor", "")):
            self._error(ValueError("Guardá la Configuración antes de emitir con otro CUIT."))
            return
        formulario = {clave: variable.get() for clave, variable in self._campos.items()}
        formulario["ambiente"] = self._valor_ambiente()
        formulario["items"] = [dict(item) for item in self._items]
        try:
            validar_formulario(formulario, self._config)
        except Exception as error:
            self._error(error)
            return
        config = dict(self._config)
        self._ocupado(True, "Consultando ARCA, padrón y último número autorizado...")

        def trabajo():
            try:
                cliente, auth, registro = preparar(formulario, config)
                self.after(0, lambda: self._confirmar(cliente, auth, registro))
            except Exception as error:
                self.after(0, lambda error=error: self._error(error))

        threading.Thread(target=trabajo, daemon=True).start()

    def _confirmar(self, cliente, auth, datos):
        entorno = "PRODUCCIÓN · CAE real" if datos["ambiente"] == "produccion" else "HOMOLOGACIÓN · prueba"
        asociado = datos.get("comprobante_asociado")
        resumen = (
            f"{entorno}\n\n{datos['nombre_comprobante']} "
            f"{datos['punto']:05d}-{datos['numero']:08d}\n"
            f"Emisor: {datos['datos_emisor']['nombre']} · CUIT {datos['emisor']}\n"
            f"Domicilio comercial: {datos['datos_emisor']['domicilio_comercial']}\n"
            f"Receptor: {datos['datos_receptor']['nombre']} · Documento {datos['receptor']}\n"
            f"Domicilio comercial del receptor: {datos['datos_receptor'].get('domicilio_comercial', 'No informado')}\n"
            f"Condición IVA del receptor: {datos['condicion_iva_receptor_nombre']}\n"
            f"Fecha del comprobante: {datetime.strptime(datos['fecha'], '%Y%m%d').strftime('%d/%m/%Y')}\n"
            f"Importe total: $ {numero_local(datos['importe'])}\n"
            f"Condición de venta: {datos['condicion_venta']}"
        )
        for item in datos["items"]:
            resumen += (f"\n\n{item['descripcion']}\n"
                        f"{item['cantidad']} {item['unidad']} × $ {numero_local(item['precio_unitario'])}"
                        f" = $ {numero_local(item['importe'])}")
        if datos["tipo_doc_receptor"] == 80 and not datos["datos_receptor"].get("padron_verificado", True):
            resumen += (
                "\n\nATENCIÓN: el padrón no emitió constancia para el receptor. "
                "Se usarán los datos cargados manualmente; verificá nombre, domicilio "
                "comercial y condición IVA antes de solicitar el CAE.\n"
                f"Respuesta del padrón: {datos['datos_receptor'].get('error_padron', 'No disponible')}"
            )
        if datos.get("concepto") == "Servicios":
            desde = datetime.strptime(datos["servicio_desde"], "%Y%m%d").strftime("%d/%m/%Y")
            hasta = datetime.strptime(datos["servicio_hasta"], "%Y%m%d").strftime("%d/%m/%Y")
            resumen += f"\nPeríodo del servicio: {desde} al {hasta}"
            resumen += f"\nTipo de servicio: {datos['tipo_servicio']}"
            vencimiento = datetime.strptime(datos["vencimiento_pago"], "%Y%m%d").strftime("%d/%m/%Y")
            resumen += f"\nVencimiento para el pago: {vencimiento}"
        if asociado:
            resumen += f"\nFactura asociada: {asociado['punto']:05d}-{asociado['numero']:08d}"
        for rol, perfil in (("emisor", datos["datos_emisor"]), ("receptor", datos["datos_receptor"])):
            fiscal = str(perfil.get("domicilio_fiscal", "")).strip()
            comercial = str(perfil.get("domicilio_comercial", "")).strip()
            if fiscal and comercial and fiscal.casefold() != comercial.casefold():
                resumen += f"\nDomicilio fiscal {rol} informado por ARCA: {fiscal}"
        if not self._revisar_resumen(resumen):
            self._ocupado(False, "Operación cancelada antes de solicitar CAE.")
            return
        self._ocupado(True, "Solicitando CAE a ARCA. Esperá la respuesta...")

        def trabajo():
            try:
                pdf, registro = solicitar(cliente, auth, datos)
                self.after(0, lambda: self._exito(pdf, registro, datos))
            except Exception as error:
                self.after(0, lambda error=error: self._error(error))

        threading.Thread(target=trabajo, daemon=True).start()

    def _revisar_resumen(self, resumen):
        ventana = tk.Toplevel(self)
        ventana.title("Confirmar solicitud de CAE")
        ventana.geometry("760x620")
        ventana.transient(self)
        marco = ttk.Frame(ventana, padding=16)
        marco.pack(fill="both", expand=True)
        marco.rowconfigure(0, weight=1)
        marco.columnconfigure(0, weight=1)
        texto = tk.Text(marco, wrap="word", font=("Segoe UI", 10))
        texto.grid(row=0, column=0, sticky="nsew")
        texto.insert("1.0", resumen)
        texto.configure(state="disabled")
        barra = ttk.Scrollbar(marco, orient="vertical", command=texto.yview)
        barra.grid(row=0, column=1, sticky="ns")
        texto.configure(yscrollcommand=barra.set)
        confirmado = False

        def confirmar():
            nonlocal confirmado
            confirmado = True
            ventana.destroy()

        botones = ttk.Frame(marco)
        botones.grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(botones, text="Cancelar", command=ventana.destroy).pack(side="left", padx=8)
        ttk.Button(botones, text="Solicitar CAE a ARCA", command=confirmar).pack(side="left")
        ventana.grab_set()
        self.wait_window(ventana)
        return confirmado

    def _exito(self, pdf, registro, datos):
        self._ocupado(False, f"Autorizado · CAE {datos['cae']} · {pdf}")
        if messagebox.askyesno("Comprobante autorizado", f"CAE {datos['cae']}\n\nPDF guardado en:\n{pdf}\n\n¿Abrir el PDF?", parent=self):
            os.startfile(pdf)

    def _recuperar(self):
        if self._trabajando:
            return
        ambiente = self._valor_ambiente()
        self._ocupado(True, "Consultando la solicitud pendiente en ARCA...")

        def trabajo():
            try:
                resultado = recuperar_pendiente(ambiente)
                self.after(0, lambda: self._fin_recuperacion(resultado))
            except Exception as error:
                self.after(0, lambda error=error: self._error(error))

        threading.Thread(target=trabajo, daemon=True).start()

    def _fin_recuperacion(self, resultado):
        self._ocupado(False, resultado)
        messagebox.showinfo("Recuperación", resultado, parent=self)

    def _abrir_carpeta(self):
        carpeta = BASE / ("facturas_produccion" if self._valor_ambiente() == "produccion" else "facturas_test")
        carpeta.mkdir(exist_ok=True)
        os.startfile(carpeta)


if __name__ == "__main__":
    bloqueo = open(BASE / "facturador.lock", "a+b")
    if bloqueo.tell() == 0:
        bloqueo.write(b"0")
        bloqueo.flush()
    bloqueo.seek(0)
    try:
        msvcrt.locking(bloqueo.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        raiz = tk.Tk()
        raiz.withdraw()
        messagebox.showinfo("Facturador ARCA", "El facturador ya está abierto.", parent=raiz)
        raiz.destroy()
    else:
        try:
            Facturador().mainloop()
        finally:
            bloqueo.seek(0)
            msvcrt.locking(bloqueo.fileno(), msvcrt.LK_UNLCK, 1)
    bloqueo.close()
