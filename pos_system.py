"""
==================================================================
 SISTEMA DE PUNTO DE VENTA (POS) - VERSIÓN COMERCIAL
==================================================================
Nuevas Características:
    - Login y Control de Roles (Administrador vs Cajero).
    - CRUD de Inventario (Agregar, Editar, Eliminar productos).
    - Cierre de Caja (Reporte de ventas del día).
    - Generación de Ticket de Venta (.txt).
==================================================================
"""

import sqlite3
from datetime import datetime
import os

import customtkinter as ctk
from tkinter import messagebox, ttk

# ==================================================================
# 1) CAPA DE BASE DE DATOS
# ==================================================================
class Database:
    NOMBRE_BD = "pos_system.db"

    def __init__(self):
        self.conexion = sqlite3.connect(self.NOMBRE_BD, check_same_thread=False)
        self.conexion.execute("PRAGMA foreign_keys = ON")
        self.cursor = self.conexion.cursor()
        self.crear_tablas()
        self.insertar_datos_iniciales()

    def crear_tablas(self):
        """Crea las tablas iniciales y aplica migraciones si el archivo .db es de una versión vieja."""
        # 1. Creación de la estructura base
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                precio REAL NOT NULL,
                stock INTEGER NOT NULL
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS Ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                total REAL NOT NULL
                -- Nota: usuario_id se añade dinámicamente si falta
            )
        """)
        
        # 2. MIGRACIONES (Actualización silenciosa de bases de datos viejas)
        # Intentamos agregar la nueva columna 'usuario_id'. 
        # Si la columna ya existe, SQLite lanzará un error (OperationalError).
        # Lo capturamos y lo ignoramos, así el programa sigue funcionando sin molestar al cliente.
        try:
            self.cursor.execute("ALTER TABLE Ventas ADD COLUMN usuario_id INTEGER REFERENCES Usuarios(id)")
            print("[MIGRACIÓN] Columna 'usuario_id' agregada exitosamente a la tabla Ventas existente.")
        except sqlite3.OperationalError:
            # La columna ya existe, no hay que hacer nada.
            pass

        self.conexion.commit()

    def insertar_datos_iniciales(self):
        # Insertar usuarios por defecto si no existen
        self.cursor.execute("SELECT COUNT(*) FROM Usuarios")
        if self.cursor.fetchone()[0] == 0:
            usuarios = [
                ("admin", "admin123", "administrador"),
                ("caja1", "caja123", "cajero")
            ]
            self.cursor.executemany("INSERT INTO Usuarios (username, password, rol) VALUES (?, ?, ?)", usuarios)
        
        # Insertar productos si no existen
        self.cursor.execute("SELECT COUNT(*) FROM Productos")
        if self.cursor.fetchone()[0] == 0:
            productos = [
                ("Agua Cristal 1L", 0.75, 80),
                ("Pan Francés (unidad)", 0.15, 200),
                ("Papas Fritas 45g", 0.90, 60),
                ("Café Molido 250g", 3.50, 25),
            ]
            self.cursor.executemany("INSERT INTO Productos (nombre, precio, stock) VALUES (?, ?, ?)", productos)
        self.conexion.commit()

    def verificar_credenciales(self, username, password):
        self.cursor.execute("SELECT id, username, rol FROM Usuarios WHERE username = ? AND password = ?", (username, password))
        return self.cursor.fetchone()

    # --- CRUD Productos ---
    def buscar_productos_por_nombre(self, texto_busqueda=""):
        patron = f"%{texto_busqueda.strip()}%"
        self.cursor.execute("SELECT id, nombre, precio, stock FROM Productos WHERE nombre LIKE ? COLLATE NOCASE ORDER BY nombre ASC", (patron,))
        return self.cursor.fetchall()

    def obtener_producto_por_id(self, producto_id):
        self.cursor.execute("SELECT id, nombre, precio, stock FROM Productos WHERE id = ?", (producto_id,))
        return self.cursor.fetchone()

    def guardar_producto(self, nombre, precio, stock, producto_id=None):
        if producto_id:
            self.cursor.execute("UPDATE Productos SET nombre=?, precio=?, stock=? WHERE id=?", (nombre, precio, stock, producto_id))
        else:
            self.cursor.execute("INSERT INTO Productos (nombre, precio, stock) VALUES (?, ?, ?)", (nombre, precio, stock))
        self.conexion.commit()

    def eliminar_producto(self, producto_id):
        self.cursor.execute("DELETE FROM Productos WHERE id=?", (producto_id,))
        self.conexion.commit()

    # --- Ventas y Reportes ---
    def procesar_venta(self, carrito, total, usuario_id):
        try:
            fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.cursor.execute("INSERT INTO Ventas (usuario_id, fecha, total) VALUES (?, ?, ?)", (usuario_id, fecha, total))
            
            for producto_id, datos in carrito.items():
                self.cursor.execute("UPDATE Productos SET stock = stock - ? WHERE id = ? AND stock >= ?", (datos["cantidad"], producto_id, datos["cantidad"]))
                if self.cursor.rowcount == 0:
                    raise sqlite3.Error(f"Stock insuficiente para {datos['nombre']}")
            self.conexion.commit()
            return True, fecha
        except sqlite3.Error as error:
            self.conexion.rollback()
            return False, str(error)

    def reporte_ventas_hoy(self):
        fecha_hoy = datetime.now().strftime("%Y-%m-%d")
        patron = f"{fecha_hoy}%"
        self.cursor.execute("SELECT COUNT(*), SUM(total) FROM Ventas WHERE fecha LIKE ?", (patron,))
        return self.cursor.fetchone()

    def cerrar_conexion(self):
        self.conexion.close()


# ==================================================================
# 2) CAPA DE INTERFAZ GRÁFICA
# ==================================================================
class POSApp(ctk.CTk):
    TASA_IVA = 0.13  # 13% IVA 
    COLUMNAS_CATALOGO = 2

    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title("Sistema POS - Pro Version")
        self.geometry("1100x650")
        self.minsize(1000, 600)

        self.bd = Database()
        self.usuario_actual = None
        self.carrito = {}

        self.protocol("WM_DELETE_WINDOW", self.al_cerrar_ventana)
        self.mostrar_pantalla_login()

    # ==============================================================
    # PANTALLA DE LOGIN
    # ==============================================================
    def mostrar_pantalla_login(self):
        self.frame_login = ctk.CTkFrame(self)
        self.frame_login.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(self.frame_login, text="INICIAR SESIÓN", font=ctk.CTkFont(size=24, weight="bold", family="Helvetica")).pack(pady=(30, 10), padx=50)
        
        self.entry_user = ctk.CTkEntry(self.frame_login, placeholder_text="Usuario", width=250, height=40)
        self.entry_user.pack(pady=10, padx=30)
        
        self.entry_pass = ctk.CTkEntry(self.frame_login, placeholder_text="Contraseña", show="*", width=250, height=40)
        self.entry_pass.pack(pady=10, padx=30)

        ctk.CTkButton(self.frame_login, text="Ingresar al Sistema", height=45, fg_color="#1F6AA5", font=ctk.CTkFont(weight="bold"), command=self.verificar_login).pack(pady=(20, 30), padx=30, fill="x")

    def verificar_login(self):
        user = self.entry_user.get()
        pwd = self.entry_pass.get()
        usuario = self.bd.verificar_credenciales(user, pwd)

        if usuario:
            self.usuario_actual = {"id": usuario[0], "username": usuario[1], "rol": usuario[2]}
            self.frame_login.destroy()
            self.construir_interfaz_principal()
        else:
            messagebox.showerror("Error", "Credenciales incorrectas")

    # ==============================================================
    # INTERFAZ PRINCIPAL Y NAVEGACIÓN
    # ==============================================================
    def construir_interfaz_principal(self):
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Panel Izquierdo (Menú)
        self.frame_menu = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#111111")
        self.frame_menu.grid(row=0, column=0, sticky="nsw")
        self.frame_menu.grid_propagate(False)

        # Perfil de usuario estilizado
        lbl_brand = ctk.CTkLabel(self.frame_menu, text="SISTEMA POS", font=ctk.CTkFont(size=20, weight="bold"), text_color="#3B8ED0")
        lbl_brand.pack(pady=(30, 5), padx=20)
        ctk.CTkLabel(self.frame_menu, text=f"Usuario: {self.usuario_actual['username']}\nRol: {self.usuario_actual['rol'].capitalize()}", font=ctk.CTkFont(size=12), text_color="gray60", justify="center").pack(pady=(0, 30), padx=20)

        # Contenedor central (donde cambian las vistas)
        self.contenedor_vistas = ctk.CTkFrame(self, fg_color="transparent")
        self.contenedor_vistas.grid(row=0, column=1, sticky="nsew")

        # Botones de Menú Dinámicos
        self.btn_venta = ctk.CTkButton(self.frame_menu, text="🛒 Punto de Venta", height=45, anchor="w", command=self.mostrar_vista_ventas)
        self.btn_venta.pack(pady=5, padx=15, fill="x")

        if self.usuario_actual["rol"] == "administrador":
            self.btn_inv = ctk.CTkButton(self.frame_menu, text="📦 Gestión Inventario", height=45, anchor="w", fg_color="transparent", border_width=1, command=self.mostrar_vista_inventario)
            self.btn_inv.pack(pady=5, padx=15, fill="x")
            
            self.btn_rep = ctk.CTkButton(self.frame_menu, text="📊 Cierre y Reportes", height=45, anchor="w", fg_color="transparent", border_width=1, command=self.mostrar_vista_reportes)
            self.btn_rep.pack(pady=5, padx=15, fill="x")

        btn_salir = ctk.CTkButton(self.frame_menu, text="🚪 Cerrar Sesión", height=45, anchor="w", fg_color="#8F2D2D", hover_color="#6B1F1F", command=self.cerrar_sesion)
        btn_salir.pack(side="bottom", pady=20, padx=15, fill="x")

        # Iniciar en ventas
        self.vista_actual = None
        self.mostrar_vista_ventas()

    def limpiar_vistas(self):
        for widget in self.contenedor_vistas.winfo_children():
            widget.destroy()
        # Resetear estilos de botones
        self.btn_venta.configure(fg_color="transparent", border_width=1)
        if self.usuario_actual["rol"] == "administrador":
            self.btn_inv.configure(fg_color="transparent", border_width=1)
            self.btn_rep.configure(fg_color="transparent", border_width=1)

    # ==============================================================
    # MÓDULO 1: PUNTO DE VENTA (Actualizado)
    # ==============================================================
    def mostrar_vista_ventas(self):
        self.limpiar_vistas()
        self.btn_venta.configure(fg_color=["#3B8ED0", "#1F6AA5"], border_width=0)
        
        self.contenedor_vistas.grid_columnconfigure(0, weight=3)
        self.contenedor_vistas.grid_columnconfigure(1, weight=2)
        self.contenedor_vistas.grid_rowconfigure(0, weight=1)

        # Panel Central (Catálogo)
        frame_central = ctk.CTkFrame(self.contenedor_vistas, corner_radius=0)
        frame_central.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        frame_central.grid_rowconfigure(1, weight=1)
        frame_central.grid_columnconfigure(0, weight=1)

        self.entrada_busqueda = ctk.CTkEntry(frame_central, placeholder_text="Buscar producto...", height=40)
        self.entrada_busqueda.grid(row=0, column=0, sticky="ew", padx=15, pady=15)
        self.entrada_busqueda.bind("<KeyRelease>", lambda e: self.cargar_catalogo())

        self.frame_resultados = ctk.CTkScrollableFrame(frame_central, label_text="Catálogo Rápido")
        self.frame_resultados.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 15))
        for c in range(self.COLUMNAS_CATALOGO):
            self.frame_resultados.grid_columnconfigure(c, weight=1)

        # Panel Derecho (Carrito)
        self.frame_carrito = ctk.CTkFrame(self.contenedor_vistas, corner_radius=0)
        self.frame_carrito.grid(row=0, column=1, sticky="nsew", padx=(0, 2), pady=2)
        self.frame_carrito.grid_rowconfigure(1, weight=1)
        self.frame_carrito.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self.frame_carrito, text="Terminal de Cobro", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=15, pady=(15, 5))
        
        self.frame_carrito_items = ctk.CTkScrollableFrame(self.frame_carrito, label_text="")
        self.frame_carrito_items.grid(row=1, column=0, sticky="nsew", padx=15, pady=(0, 10))
        self.frame_carrito_items.grid_columnconfigure(0, weight=1)

        frame_totales = ctk.CTkFrame(self.frame_carrito, fg_color="transparent")
        frame_totales.grid(row=2, column=0, sticky="ew", padx=15, pady=10)
        frame_totales.grid_columnconfigure(0, weight=1)

        self.label_subtotal = ctk.CTkLabel(frame_totales, text="Subtotal: $0.00", font=ctk.CTkFont(size=14))
        self.label_subtotal.grid(row=0, column=0, sticky="e")
        self.label_iva = ctk.CTkLabel(frame_totales, text=f"IVA ({int(self.TASA_IVA*100)}%): $0.00", text_color="gray60")
        self.label_iva.grid(row=1, column=0, sticky="e")
        self.label_total = ctk.CTkLabel(frame_totales, text="Total: $0.00", font=ctk.CTkFont(size=24, weight="bold"), text_color="#2CC985")
        self.label_total.grid(row=2, column=0, sticky="e", pady=(5, 0))

        ctk.CTkButton(self.frame_carrito, text="PROCESAR COBRO", height=60, font=ctk.CTkFont(size=16, weight="bold"), fg_color="#2CC985", hover_color="#219A67", command=self.procesar_cobro).grid(row=3, column=0, sticky="ew", padx=15, pady=(5, 15))

        self.cargar_catalogo()
        self.actualizar_panel_carrito()

    def cargar_catalogo(self):
        for widget in self.frame_resultados.winfo_children(): widget.destroy()
        productos = self.bd.buscar_productos_por_nombre(self.entrada_busqueda.get())
        
        for indice, (pid, nombre, precio, stock) in enumerate(productos):
            fila, col = divmod(indice, self.COLUMNAS_CATALOGO)
            hay_stock = stock > 0
            btn = ctk.CTkButton(
                self.frame_resultados, text=f"{nombre}\n${precio:.2f}  |  Disp: {stock}",
                height=70, anchor="w", state="normal" if hay_stock else "disabled",
                fg_color=("#2b2b2b") if hay_stock else "gray20",
                hover_color="#3B8ED0", border_width=1, border_color="#3B8ED0" if hay_stock else "gray30",
                command=lambda id=pid: self.agregar_al_carrito(id)
            )
            btn.grid(row=fila, column=col, padx=5, pady=5, sticky="nsew")

    def agregar_al_carrito(self, producto_id):
        producto = self.bd.obtener_producto_por_id(producto_id)
        if not producto: return
        _, nombre, precio, stock = producto
        cant_actual = self.carrito.get(producto_id, {}).get("cantidad", 0)

        if cant_actual >= stock:
            messagebox.showwarning("Stock", "No hay más unidades disponibles.")
            return

        if producto_id in self.carrito: self.carrito[producto_id]["cantidad"] += 1
        else: self.carrito[producto_id] = {"nombre": nombre, "precio": precio, "cantidad": 1}
        self.actualizar_panel_carrito()

    def quitar_del_carrito(self, pid):
        if pid in self.carrito:
            del self.carrito[pid]
            self.actualizar_panel_carrito()

    def actualizar_panel_carrito(self):
        for widget in self.frame_carrito_items.winfo_children(): widget.destroy()
        subtotal = 0.0

        for pid, datos in self.carrito.items():
            st_art = datos["precio"] * datos["cantidad"]
            subtotal += st_art
            f = ctk.CTkFrame(self.frame_carrito_items, fg_color="transparent")
            f.pack(fill="x", pady=2)
            f.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(f, text=f"{datos['nombre']}\n{datos['cantidad']} x ${datos['precio']:.2f}", justify="left", anchor="w").grid(row=0, column=0, sticky="ew")
            ctk.CTkLabel(f, text=f"${st_art:.2f}", font=ctk.CTkFont(weight="bold")).grid(row=0, column=1, padx=10)
            ctk.CTkButton(f, text="✕", width=30, fg_color="#8F2D2D", hover_color="#6B1F1F", command=lambda id=pid: self.quitar_del_carrito(id)).grid(row=0, column=2)

        iva = subtotal * self.TASA_IVA
        total = subtotal + iva
        self.label_subtotal.configure(text=f"Subtotal: ${subtotal:.2f}")
        self.label_iva.configure(text=f"IVA ({int(self.TASA_IVA*100)}%): ${iva:.2f}")
        self.label_total.configure(text=f"Total: ${total:.2f}")

    def procesar_cobro(self):
        if not self.carrito: return messagebox.showwarning("Aviso", "Carrito vacío")
        
        subtotal = sum(d["precio"] * d["cantidad"] for d in self.carrito.values())
        total = subtotal + (subtotal * self.TASA_IVA)
        
        exito, resultado = self.bd.procesar_venta(self.carrito, total, self.usuario_actual["id"])
        
        if exito:
            self.generar_ticket_txt(resultado, subtotal, total)
            messagebox.showinfo("Éxito", f"Venta registrada. Cambio exacto: ${total:.2f}\nTicket generado.")
            self.carrito.clear()
            self.actualizar_panel_carrito()
            self.cargar_catalogo()
        else:
            messagebox.showerror("Error", f"Error al procesar: {resultado}")

    def generar_ticket_txt(self, fecha, subtotal, total):
        """Simula la impresión enviando los datos a un archivo de texto"""
        ticket = f"====== MI NEGOCIO ======\nFecha: {fecha}\nCajero: {self.usuario_actual['username']}\n------------------------\n"
        for d in self.carrito.values():
            ticket += f"{d['cantidad']}x {d['nombre'][:15]}... ${d['precio']*d['cantidad']:.2f}\n"
        ticket += f"------------------------\nSubtotal: ${subtotal:.2f}\nIVA: ${total-subtotal:.2f}\nTOTAL: ${total:.2f}\n========================"
        
        with open("ticket_ultima_venta.txt", "w", encoding="utf-8") as f:
            f.write(ticket)

    # ==============================================================
    # MÓDULO 2: GESTIÓN DE INVENTARIO (CRUD)
    # ==============================================================
    def mostrar_vista_inventario(self):
        self.limpiar_vistas()
        self.btn_inv.configure(fg_color=["#3B8ED0", "#1F6AA5"], border_width=0)
        
        self.contenedor_vistas.grid_columnconfigure(0, weight=1)
        self.contenedor_vistas.grid_columnconfigure(1, weight=2)
        self.contenedor_vistas.grid_rowconfigure(0, weight=1)

        # Panel Izquierdo: Formulario CRUD
        frame_form = ctk.CTkFrame(self.contenedor_vistas)
        frame_form.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        
        ctk.CTkLabel(frame_form, text="Nuevo / Editar Producto", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=20)
        
        self.id_edicion = None
        self.ent_nombre = ctk.CTkEntry(frame_form, placeholder_text="Nombre del Producto")
        self.ent_nombre.pack(pady=10, padx=20, fill="x")
        self.ent_precio = ctk.CTkEntry(frame_form, placeholder_text="Precio de Venta ($)")
        self.ent_precio.pack(pady=10, padx=20, fill="x")
        self.ent_stock = ctk.CTkEntry(frame_form, placeholder_text="Stock Inicial")
        self.ent_stock.pack(pady=10, padx=20, fill="x")

        ctk.CTkButton(frame_form, text="💾 Guardar Producto", fg_color="#2CC985", hover_color="#219A67", command=self.guardar_producto_crud).pack(pady=20, padx=20, fill="x")
        ctk.CTkButton(frame_form, text="Limpiar Formulario", fg_color="transparent", border_width=1, command=self.limpiar_form_crud).pack(padx=20, fill="x")

        # Panel Derecho: Lista de inventario
        frame_lista = ctk.CTkScrollableFrame(self.contenedor_vistas, label_text="Inventario Existente")
        frame_lista.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        self.frame_lista_inv = frame_lista
        self.cargar_lista_inventario()

    def guardar_producto_crud(self):
        try:
            nom = self.ent_nombre.get().strip()
            pre = float(self.ent_precio.get())
            stk = int(self.ent_stock.get())
            if not nom or pre < 0 or stk < 0: raise ValueError
            
            self.bd.guardar_producto(nom, pre, stk, self.id_edicion)
            self.limpiar_form_crud()
            self.cargar_lista_inventario()
            messagebox.showinfo("Éxito", "Inventario actualizado")
        except ValueError:
            messagebox.showerror("Error", "Datos inválidos. Verifica precio y stock.")

    def cargar_lista_inventario(self):
        for widget in self.frame_lista_inv.winfo_children(): widget.destroy()
        for pid, nom, pre, stk in self.bd.buscar_productos_por_nombre(""):
            f = ctk.CTkFrame(self.frame_lista_inv)
            f.pack(fill="x", pady=5, padx=5)
            f.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(f, text=f"{nom} | ${pre:.2f} | Stock: {stk}", anchor="w").grid(row=0, column=0, padx=10, pady=10, sticky="w")
            ctk.CTkButton(f, text="Editar", width=60, command=lambda id=pid, n=nom, p=pre, s=stk: self.cargar_form_edicion(id, n, p, s)).grid(row=0, column=1, padx=5)
            ctk.CTkButton(f, text="Borrar", width=60, fg_color="#8F2D2D", hover_color="#6B1F1F", command=lambda id=pid: self.borrar_producto_crud(id)).grid(row=0, column=2, padx=5)

    def cargar_form_edicion(self, pid, nom, pre, stk):
        self.limpiar_form_crud()
        self.id_edicion = pid
        self.ent_nombre.insert(0, nom)
        self.ent_precio.insert(0, str(pre))
        self.ent_stock.insert(0, str(stk))

    def borrar_producto_crud(self, pid):
        if messagebox.askyesno("Confirmar", "¿Eliminar este producto?"):
            self.bd.eliminar_producto(pid)
            self.cargar_lista_inventario()

    def limpiar_form_crud(self):
        self.id_edicion = None
        self.ent_nombre.delete(0, 'end')
        self.ent_precio.delete(0, 'end')
        self.ent_stock.delete(0, 'end')

    # ==============================================================
    # MÓDULO 3: CIERRE DE CAJA Y REPORTES
    # ==============================================================
    def mostrar_vista_reportes(self):
        self.limpiar_vistas()
        self.btn_rep.configure(fg_color=["#3B8ED0", "#1F6AA5"], border_width=0)
        self.contenedor_vistas.grid_columnconfigure(0, weight=1)
        self.contenedor_vistas.grid_rowconfigure(0, weight=1)

        frame_rep = ctk.CTkFrame(self.contenedor_vistas)
        frame_rep.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)

        ctk.CTkLabel(frame_rep, text="Resumen del Día", font=ctk.CTkFont(size=24, weight="bold")).pack(pady=(40, 20))
        
        ventas_hoy, total_hoy = self.bd.reporte_ventas_hoy()
        total_hoy = total_hoy or 0.0

        f_datos = ctk.CTkFrame(frame_rep, fg_color="#1a1a1a", corner_radius=10)
        f_datos.pack(pady=20, padx=50, fill="x")
        
        ctk.CTkLabel(f_datos, text=f"Total de tickets emitidos hoy: {ventas_hoy}", font=ctk.CTkFont(size=16)).pack(pady=15)
        ctk.CTkLabel(f_datos, text=f"INGRESOS TOTALES (USD): ${total_hoy:.2f}", font=ctk.CTkFont(size=28, weight="bold"), text_color="#2CC985").pack(pady=(0, 20))

        ctk.CTkButton(frame_rep, text="🖨️ Imprimir Cierre de Caja", height=50, command=lambda: messagebox.showinfo("Cierre", "Función de impresión a térmica conectada.")).pack(pady=30)

    # ==============================================================
    # UTILIDADES
    # ==============================================================
    def cerrar_sesion(self):
        self.usuario_actual = None
        self.carrito.clear()
        for widget in self.winfo_children(): widget.destroy()
        self.mostrar_pantalla_login()

    def al_cerrar_ventana(self):
        self.bd.cerrar_conexion()
        self.destroy()

if __name__ == "__main__":
    app = POSApp()
    app.mainloop()
