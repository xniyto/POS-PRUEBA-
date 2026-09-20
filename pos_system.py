"""
==================================================================
 SISTEMA DE PUNTO DE VENTA (POS) - Escritorio
==================================================================
Stack:
    - Interfaz gráfica: CustomTkinter
    - Base de datos local: SQLite3 (archivo pos_system.db)
    - Arquitectura: Programación Orientada a Objetos (POO)

Estructura del archivo:
    1) Clase Database  -> toda la comunicación con SQLite.
    2) Clase POSApp     -> toda la interfaz gráfica y la lógica de
                           negocio (carrito, cobro, navegación).
    3) Bloque __main__  -> punto de entrada de la aplicación.

Para ejecutar necesitas tener instalado CustomTkinter:
    pip install customtkinter
==================================================================
"""

import sqlite3
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox


# ==================================================================
# 1) CAPA DE BASE DE DATOS
# ==================================================================
class Database:
    """
    Encapsula TODA la comunicación con SQLite. La interfaz (POSApp)
    nunca escribe SQL directamente: solo llama a los métodos de esta
    clase. Esto separa "qué se muestra en pantalla" de "cómo se
    guardan/leen los datos", que es la idea central de dividir el
    sistema en capas.
    """

    NOMBRE_BD = "pos_system.db"

    def __init__(self):
        # check_same_thread=False: la conexión se crea aquí pero se
        # reutiliza durante toda la vida de la app dentro del loop de
        # eventos de Tkinter. Como es una app de un solo hilo, esto es
        # seguro y evita reabrir la conexión en cada consulta.
        self.conexion = sqlite3.connect(self.NOMBRE_BD, check_same_thread=False)
        self.conexion.execute("PRAGMA foreign_keys = ON")
        self.cursor = self.conexion.cursor()

        self.crear_tablas()
        self.insertar_productos_prueba()

    # --------------------------------------------------------------
    # Creación de tablas
    # --------------------------------------------------------------
    def crear_tablas(self):
        """Crea las tablas Productos y Ventas si todavía no existen."""
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Productos (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre  TEXT    NOT NULL,
                precio  REAL    NOT NULL,
                stock   INTEGER NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Ventas (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha  TEXT    NOT NULL,
                total  REAL    NOT NULL
            )
        """)
        self.conexion.commit()

    # --------------------------------------------------------------
    # Datos de prueba
    # --------------------------------------------------------------
    def insertar_productos_prueba(self):
        """
        Llena el catálogo con productos de ejemplo, mostrar
        el catálogo la primera vez que se ejecuta la app.
        Verifica primero si ya hay productos para no duplicarlos
        cada vez que se abre el programa.
        """
        self.cursor.execute("SELECT COUNT(*) FROM Productos")
        cantidad_existente = self.cursor.fetchone()[0]
        if cantidad_existente > 0:
            return

        productos_prueba = [
            ("Refresco SEMENNNN LOL 600ml",     1.25,  50),
            ("Agua NORMAL 1L",     0.75,  80),
            ("Pan Frances BIEN RICO JEJE (unidad)",    0.15, 200),
            ("Papas Fritas 45g",        0.90,  60),
            ("Cafe Molido 250g",        3.50,  25),
            ("Chicle Menta",            0.50, 100),
            ("Leche Entera 1L",         1.85,  30),
            ("Huevos (docena)",         2.75,  25),
            ("Arroz 1lb",               0.95,  45),
            ("Frijoles Enlatados",      1.40,  35),
            ("Jabon de Bano",           1.20,  55),
            ("Detergente en Polvo 1kg", 3.75,  20),
            ("Galletas Dulces 200g",    1.15,  40),
            ("Cepillo Dental",          1.60,   0),  # ejemplo de producto agotado
        ]
        self.cursor.executemany(
            "INSERT INTO Productos (nombre, precio, stock) VALUES (?, ?, ?)",
            productos_prueba
        )
        self.conexion.commit()

    # --------------------------------------------------------------
    # Consultas de productos
    # --------------------------------------------------------------
    def buscar_productos_por_nombre(self, texto_busqueda=""):
        """
        Devuelve todos los productos cuyo nombre contiene el texto
        buscado (insensible a mayusculas). Si el texto viene vacio,
        el '%%' hace que el LIKE coincida con todos los productos,
        por lo que este mismo método sirve para "traer el catálogo
        completo" y para "filtrar por búsqueda".
        """
        patron = f"%{texto_busqueda.strip()}%"
        self.cursor.execute(
            "SELECT id, nombre, precio, stock FROM Productos "
            "WHERE nombre LIKE ? COLLATE NOCASE ORDER BY nombre ASC",
            (patron,)
        )
        return self.cursor.fetchall()

    def obtener_producto_por_id(self, producto_id):
        """
        Trae el estado MÁS ACTUAL de un producto directamente de la
        base de datos. Se usa al presionar un botón del catálogo para
        confirmar el stock real disponible en ese instante, en vez de
        confiar en el dato que se mostró la última vez que se dibujó
        la pantalla.
        """
        self.cursor.execute(
            "SELECT id, nombre, precio, stock FROM Productos WHERE id = ?",
            (producto_id,)
        )
        return self.cursor.fetchone()

    # --------------------------------------------------------------
    # Registro de ventas y descuento de stock
    # --------------------------------------------------------------
    def registrar_venta(self, total, fecha=None):
        """Inserta una fila en Ventas y devuelve el id generado."""
        if fecha is None:
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            "INSERT INTO Ventas (fecha, total) VALUES (?, ?)",
            (fecha, total)
        )
        return self.cursor.lastrowid

    def descontar_stock(self, producto_id, cantidad_vendida):
        """
        Resta 'cantidad_vendida' del stock de un producto.
        La condición 'AND stock >= ?' evita que el stock quede
        negativo; si no se actualiza ninguna fila (rowcount == 0)
        significa que ya no había stock suficiente, y se lanza un
        error para que la venta completa se pueda revertir.
        """
        self.cursor.execute(
            "UPDATE Productos SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (cantidad_vendida, producto_id, cantidad_vendida)
        )
        if self.cursor.rowcount == 0:
            raise sqlite3.Error(
                f"Stock insuficiente para el producto con ID {producto_id}"
            )

    def procesar_venta(self, carrito, total):
        """
        Orquesta el cobro completo dentro de UNA sola transacción:
        registra la venta y descuenta el stock de cada artículo.
        Si algo falla a mitad de camino (por ejemplo, otro proceso
        vendió el último artículo justo antes), se hace rollback
        para que la base de datos nunca quede en un estado a medias
        (venta registrada pero stock sin descontar, o viceversa).
        """
        try:
            self.registrar_venta(total)
            for producto_id, datos in carrito.items():
                self.descontar_stock(producto_id, datos["cantidad"])
            self.conexion.commit()
            return True
        except sqlite3.Error as error:
            self.conexion.rollback()
            print(f"[ERROR AL PROCESAR VENTA] {error}")
            return False

    def cerrar_conexion(self):
        """Cierra la conexión a la base de datos de forma ordenada."""
        self.conexion.close()


# ==================================================================
# 2) CAPA DE INTERFAZ GRAFICA
# ==================================================================
class POSApp(ctk.CTk):
    """
    Ventana principal de la aplicación. Contiene tres paneles:
        - Izquierdo: menú lateral (navegación).
        - Central:   catálogo de productos con buscador.
        - Derecho:   carrito de compra y botón de cobro.

    El estado del carrito se guarda en un diccionario en memoria
    (self.carrito); solo se escribe en la base de datos hasta que
    se presiona "PROCESAR COBRO".
    """

    TASA_IVA = 0.13  # 13% - ajustar segun la normativa fiscal de cada pais
    COLUMNAS_CATALOGO = 2  # cuantas tarjetas/botones de producto por fila

    def __init__(self):
        # set_appearance_mode / set_default_color_theme configuran el
        # tema ANTES de crear cualquier widget, incluyendo la ventana
        # raiz (super().__init__()), por eso van primero.
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        # ------------------------------------------------------------
        # Conexión a la base de datos: se crea UNA sola vez al abrir
        # la app y se reutiliza en todos los métodos de la interfaz.
        # ------------------------------------------------------------
        self.bd = Database()

        # Estado interno del carrito: { id_producto: {nombre, precio, cantidad} }
        self.carrito = {}
        self.modo_actual = "venta"  # "venta" o "inventario"

        self._configurar_ventana()
        self._crear_panel_izquierdo()
        self._crear_panel_central()
        self._crear_panel_derecho()

        self.cargar_catalogo()
        self.actualizar_panel_carrito()

        # Cierra la conexión a la BD de forma ordenada al cerrar la ventana
        self.protocol("WM_DELETE_WINDOW", self.al_cerrar_ventana)

    # ------------------------------------------------------------
    # Configuración general de la ventana
    # ------------------------------------------------------------
    def _configurar_ventana(self):
        self.title("Sistema POS - Punto de Venta")
        self.geometry("1000x600")
        self.minsize(950, 550)

        # 3 columnas: menu (fija) | catalogo (flexible) | carrito (flexible)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=3)
        self.grid_columnconfigure(2, weight=2)
        self.grid_rowconfigure(0, weight=1)

    # ------------------------------------------------------------
    # PANEL IZQUIERDO: menú lateral
    # ------------------------------------------------------------
    def _crear_panel_izquierdo(self):
        self.frame_menu = ctk.CTkFrame(self, width=190, corner_radius=0)
        self.frame_menu.grid(row=0, column=0, sticky="nsw")
        self.frame_menu.grid_propagate(False)  # mantiene el ancho fijo de 190px

        ctk.CTkLabel(
            self.frame_menu, text="Mi Negocio",
            font=ctk.CTkFont(size=22, weight="bold")
        ).pack(pady=(30, 5), padx=20)

        ctk.CTkLabel(
            self.frame_menu, text="Sistema POS",
            font=ctk.CTkFont(size=13), text_color="gray60"
        ).pack(pady=(0, 40), padx=20)

        self.boton_menu_venta = ctk.CTkButton(
            self.frame_menu, text="🛒  Punto de Venta", height=42,
            anchor="w", command=self.mostrar_punto_venta
        )
        self.boton_menu_venta.pack(pady=8, padx=20, fill="x")

        self.boton_menu_inventario = ctk.CTkButton(
            self.frame_menu, text="📦  Inventario", height=42,
            anchor="w", fg_color="transparent", border_width=1,
            command=self.mostrar_inventario
        )
        self.boton_menu_inventario.pack(pady=8, padx=20, fill="x")

    # ------------------------------------------------------------
    # PANEL CENTRAL: buscador + catálogo (scrollable)
    # ------------------------------------------------------------
    def _crear_panel_central(self):
        self.frame_central = ctk.CTkFrame(self, corner_radius=0)
        self.frame_central.grid(row=0, column=1, sticky="nsew", padx=2, pady=2)
        self.frame_central.grid_rowconfigure(1, weight=1)
        self.frame_central.grid_columnconfigure(0, weight=1)

        # --- barra superior con el buscador ---
        barra_busqueda = ctk.CTkFrame(self.frame_central, fg_color="transparent")
        barra_busqueda.grid(row=0, column=0, sticky="ew", padx=15, pady=15)
        barra_busqueda.grid_columnconfigure(0, weight=1)

        self.entrada_busqueda = ctk.CTkEntry(
            barra_busqueda, placeholder_text="Buscar producto por nombre...",
            height=38
        )
        self.entrada_busqueda.grid(row=0, column=0, sticky="ew")
        # Conexión CustomTkinter -> SQLite: cada vez que el usuario suelta
        # una tecla se vuelve a llamar cargar_catalogo(), que lee el texto
        # de este Entry y lo pasa a bd.buscar_productos_por_nombre().
        # Así la búsqueda se siente "en vivo" sin necesidad de un botón.
        self.entrada_busqueda.bind("<KeyRelease>", lambda evento: self.cargar_catalogo())

        # --- area scrollable donde se dibujan los productos ---
        self.frame_resultados = ctk.CTkScrollableFrame(
            self.frame_central, label_text="Catálogo de Productos"
        )
        self.frame_resultados.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        for columna in range(self.COLUMNAS_CATALOGO):
            self.frame_resultados.grid_columnconfigure(columna, weight=1)

    # ------------------------------------------------------------
    # PANEL DERECHO: carrito de compra
    # ------------------------------------------------------------
    def _crear_panel_derecho(self):
        self.frame_carrito = ctk.CTkFrame(self, corner_radius=0)
        self.frame_carrito.grid(row=0, column=2, sticky="nsew", padx=(0, 2), pady=2)
        self.frame_carrito.grid_rowconfigure(1, weight=1)
        self.frame_carrito.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self.frame_carrito, text="Carrito de Compra",
            font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))

        # Lista de artículos agregados (se redibuja completa en cada cambio)
        self.frame_carrito_items = ctk.CTkScrollableFrame(self.frame_carrito, label_text="")
        self.frame_carrito_items.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 10))
        self.frame_carrito_items.grid_columnconfigure(0, weight=1)
        # Nota: el mensaje de "carrito vacío" se crea dinámicamente dentro
        # de actualizar_panel_carrito(), ya que depende del estado actual.

        # --- totales dinámicos ---
        frame_totales = ctk.CTkFrame(self.frame_carrito, fg_color="transparent")
        frame_totales.grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 10))
        frame_totales.grid_columnconfigure(0, weight=1)

        self.label_subtotal = ctk.CTkLabel(
            frame_totales, text="Subtotal: $0.00", font=ctk.CTkFont(size=14)
        )
        self.label_subtotal.grid(row=0, column=0, sticky="e")

        self.label_iva = ctk.CTkLabel(
            frame_totales, text=f"IVA ({int(self.TASA_IVA * 100)}%): $0.00",
            font=ctk.CTkFont(size=13), text_color="gray60"
        )
        self.label_iva.grid(row=1, column=0, sticky="e", pady=(2, 2))

        self.label_total = ctk.CTkLabel(
            frame_totales, text="Total: $0.00", font=ctk.CTkFont(size=20, weight="bold")
        )
        self.label_total.grid(row=2, column=0, sticky="e", pady=(4, 0))

        # --- botón de cobro (grande y verde, como pide el requerimiento) ---
        self.boton_cobrar = ctk.CTkButton(
            self.frame_carrito, text="Procesar Cobro", height=55,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#2CC985", hover_color="#219A67",
            command=self.procesar_cobro
        )
        self.boton_cobrar.grid(row=3, column=0, sticky="ew", padx=15, pady=(5, 15))

    # ==============================================================
    # NAVEGACION ENTRE "PUNTO DE VENTA" E "INVENTARIO"
    # ==============================================================
    def mostrar_punto_venta(self):
        """Activa el modo catálogo-para-vender (botones clicables)."""
        self.modo_actual = "venta"
        self.boton_menu_venta.configure(fg_color=["#3B8ED0", "#1F6AA5"], border_width=0)
        self.boton_menu_inventario.configure(fg_color="transparent", border_width=1)
        self.frame_resultados.configure(label_text="Catálogo de Productos")
        self.entrada_busqueda.configure(placeholder_text="Buscar producto por nombre...")
        self.cargar_catalogo()

    def mostrar_inventario(self):
        """Activa el modo de solo-consulta de inventario (sin agregar al carrito)."""
        self.modo_actual = "inventario"
        self.boton_menu_inventario.configure(fg_color=["#3B8ED0", "#1F6AA5"], border_width=0)
        self.boton_menu_venta.configure(fg_color="transparent", border_width=1)
        self.frame_resultados.configure(label_text="Inventario Actual")
        self.entrada_busqueda.configure(placeholder_text="Buscar en inventario...")
        self.cargar_catalogo()

    # ==============================================================
    # CATALOGO: leer de SQLite y dibujar en CustomTkinter
    # ==============================================================
    def cargar_catalogo(self):
        """
        Punto central donde CustomTkinter "habla" con SQLite:
        1) toma el texto que el usuario escribió en el CTkEntry,
        2) se lo pasa a Database.buscar_productos_por_nombre(),
        3) recorre las filas devueltas y crea un widget por cada una.
        Se llama al iniciar, al escribir en el buscador, al cambiar
        de modo (venta/inventario) y después de cada venta exitosa
        (para reflejar el stock actualizado).
        """
        # Limpiar resultados dibujados anteriormente antes de redibujar
        for widget in self.frame_resultados.winfo_children():
            widget.destroy()

        texto_busqueda = self.entrada_busqueda.get()
        productos = self.bd.buscar_productos_por_nombre(texto_busqueda)

        if not productos:
            ctk.CTkLabel(
                self.frame_resultados, text="No se encontraron productos."
            ).grid(row=0, column=0, columnspan=self.COLUMNAS_CATALOGO, pady=30)
            return

        for indice, producto in enumerate(productos):
            fila = indice // self.COLUMNAS_CATALOGO
            columna = indice % self.COLUMNAS_CATALOGO
            if self.modo_actual == "venta":
                self._dibujar_tarjeta_venta(producto, fila, columna)
            else:
                self._dibujar_tarjeta_inventario(producto, fila, columna)

    def _dibujar_tarjeta_venta(self, producto, fila, columna):
        """Dibuja un producto como botón clicable que agrega al carrito."""
        producto_id, nombre, precio, stock = producto
        hay_stock = stock > 0

        texto = f"{nombre}\n${precio:.2f}   |   Stock: {stock}"
        boton = ctk.CTkButton(
            self.frame_resultados, text=texto, height=64,
            anchor="w",
            state="normal" if hay_stock else "disabled",
            fg_color=("#3B8ED0", "#1F6AA5") if hay_stock else "gray30",
            # Se usa un lambda con valor por defecto (pid=producto_id) para
            # "congelar" el id de este producto especifico en este botón;
            # sin eso, todos los botones terminarían apuntando al último
            # producto del ciclo for.
            command=lambda pid=producto_id: self.agregar_al_carrito(pid)
        )
        boton.grid(row=fila, column=columna, padx=8, pady=8, sticky="nsew")

    def _dibujar_tarjeta_inventario(self, producto, fila, columna):
        """Dibuja un producto como tarjeta de solo lectura (vista Inventario)."""
        producto_id, nombre, precio, stock = producto
        tarjeta = ctk.CTkFrame(self.frame_resultados, border_width=1)
        tarjeta.grid(row=fila, column=columna, padx=8, pady=8, sticky="nsew")

        ctk.CTkLabel(
            tarjeta, text=nombre, font=ctk.CTkFont(weight="bold"), anchor="w"
        ).pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            tarjeta, text=f"Precio: ${precio:.2f}", anchor="w"
        ).pack(fill="x", padx=12)

        color_stock = "#FF6B6B" if stock <= 5 else "#8BE28B"
        texto_stock = "Agotado" if stock == 0 else f"Stock disponible: {stock}"
        ctk.CTkLabel(
            tarjeta, text=texto_stock, text_color=color_stock, anchor="w"
        ).pack(fill="x", padx=12, pady=(0, 10))

    # ==============================================================
    # LOGICA DEL CARRITO
    # ==============================================================
    def agregar_al_carrito(self, producto_id):
        """
        Se ejecuta al presionar el botón de un producto en el catálogo.
        Vuelve a consultar la base de datos (obtener_producto_por_id)
        para confirmar el stock real en este momento -en vez de confiar
        en el número que se dibujó al cargar el catálogo- y solo si hay
        unidades disponibles lo agrega (o incrementa) en self.carrito.
        """
        try:
            producto = self.bd.obtener_producto_por_id(producto_id)
            if producto is None:
                messagebox.showerror("Producto no encontrado", "Este producto ya no existe en la base de datos.")
                self.cargar_catalogo()
                return

            _, nombre, precio, stock_disponible = producto
            cantidad_en_carrito = self.carrito.get(producto_id, {}).get("cantidad", 0)

            if cantidad_en_carrito >= stock_disponible:
                messagebox.showwarning(
                    "Stock insuficiente",
                    f"No hay más unidades disponibles de '{nombre}'.\nStock actual: {stock_disponible}"
                )
                return

            if producto_id in self.carrito:
                self.carrito[producto_id]["cantidad"] += 1
            else:
                self.carrito[producto_id] = {"nombre": nombre, "precio": precio, "cantidad": 1}

            self.actualizar_panel_carrito()

        except Exception as error:
            messagebox.showerror("Error", f"No se pudo agregar el producto al carrito:\n{error}")

    def quitar_del_carrito(self, producto_id):
        """Elimina por completo un artículo del carrito (botón ✕ de cada fila)."""
        if producto_id in self.carrito:
            del self.carrito[producto_id]
            self.actualizar_panel_carrito()

    def actualizar_panel_carrito(self):
        """
        Redibuja el Panel Derecho a partir de self.carrito y recalcula
        Subtotal / IVA / Total. Se llama después de cualquier cambio en
        el carrito: agregar, quitar o vaciar tras un cobro exitoso.
        """
        for widget in self.frame_carrito_items.winfo_children():
            widget.destroy()

        if not self.carrito:
            self.label_carrito_vacio = ctk.CTkLabel(
                self.frame_carrito_items,
                text="El carrito está vacío.\nSelecciona productos del catálogo.",
                text_color="gray60", justify="center"
            )
            self.label_carrito_vacio.pack(pady=30)

        subtotal = 0.0
        for producto_id, datos in self.carrito.items():
            subtotal_articulo = datos["precio"] * datos["cantidad"]
            subtotal += subtotal_articulo

            fila = ctk.CTkFrame(self.frame_carrito_items, fg_color="transparent")
            fila.pack(fill="x", pady=4)
            fila.grid_columnconfigure(0, weight=1)

            texto_articulo = f"{datos['nombre']}\n{datos['cantidad']} x ${datos['precio']:.2f}"
            ctk.CTkLabel(fila, text=texto_articulo, justify="left", anchor="w").grid(
                row=0, column=0, sticky="ew"
            )
            ctk.CTkLabel(fila, text=f"${subtotal_articulo:.2f}", anchor="e").grid(
                row=0, column=1, padx=(6, 6)
            )
            ctk.CTkButton(
                fila, text="✕", width=26, height=26, fg_color="#B33A3A", hover_color="#8F2D2D",
                command=lambda pid=producto_id: self.quitar_del_carrito(pid)
            ).grid(row=0, column=2)

        iva = subtotal * self.TASA_IVA
        total = subtotal + iva

        self.label_subtotal.configure(text=f"Subtotal: ${subtotal:.2f}")
        self.label_iva.configure(text=f"IVA ({int(self.TASA_IVA * 100)}%): ${iva:.2f}")
        self.label_total.configure(text=f"Total: ${total:.2f}")

    # ==============================================================
    # PROCESAR COBRO
    # ==============================================================
    def procesar_cobro(self):
        """
        Valida el carrito, calcula el total, y delega en
        Database.procesar_venta() el registro de la venta y el
        descuento de stock dentro de una sola transacción.
        Envuelto en try/except para que un error inesperado (por
        ejemplo, de la base de datos) muestre un mensaje en vez de
        cerrar la aplicación de golpe.
        """
        try:
            if not self.carrito:
                messagebox.showwarning(
                    "Carrito vacío",
                    "Agrega al menos un producto antes de procesar el cobro."
                )
                return

            subtotal = sum(datos["precio"] * datos["cantidad"] for datos in self.carrito.values())
            total = subtotal + (subtotal * self.TASA_IVA)

            venta_exitosa = self.bd.procesar_venta(self.carrito, total)

            if venta_exitosa:
                messagebox.showinfo(
                    "Venta registrada",
                    f"Venta procesada con éxito.\n\nTotal cobrado: ${total:.2f}"
                )
                self.carrito.clear()
                self.actualizar_panel_carrito()
                self.cargar_catalogo()  # refresca el stock visible en el catálogo
            else:
                messagebox.showerror(
                    "No se pudo procesar la venta",
                    "Ocurrió un problema al guardar la venta (posible cambio de stock).\n"
                    "El catálogo se actualizará; por favor revisa el carrito e intenta de nuevo."
                )
                self.cargar_catalogo()

        except Exception as error:
            messagebox.showerror("Error inesperado", f"Ocurrió un error al procesar el cobro:\n{error}")

    # ==============================================================
    # CIERRE DE LA APLICACION
    # ==============================================================
    def al_cerrar_ventana(self):
        """Cierra la conexión a la base de datos antes de destruir la ventana."""
        self.bd.cerrar_conexion()
        self.destroy()


# ==================================================================
# 3) PUNTO DE ENTRADA
# ==================================================================
if __name__ == "__main__":
    app = POSApp()
    app.mainloop()
