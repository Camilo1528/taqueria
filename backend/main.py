import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, Toplevel
import logging
from app.db import db
from app.paths import ensure_dirs
from app.security import verify_password
from app.utils import cop, send_email, write_ticket

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import sv_ttk
except ImportError:
    sv_ttk = None

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Taquería Pro - Centro de Control')
        self.geometry('1380x820')
        if sv_ttk:
            sv_ttk.set_theme("dark")
            
        self.current_user = None
        self.current_order_id = None
        self.auto_refresh_kitchen() # Activa el refresco cada 30 segundos
        self.make_login()

    # --- SEGURIDAD Y LOGIN ---
    def make_login(self):
        """Bloquea la aplicación principal hasta que un cajero inicie sesión con PIN táctil."""
        self.withdraw()
        self.login_win = Toplevel(self)
        self.login_win.title("Acceso Cajero")
        self.login_win.geometry("400x550")
        self.login_win.resizable(False, False)
        self.login_win.configure(bg="#111827")
        self.login_win.protocol("WM_DELETE_WINDOW", self.destroy)

        tk.Label(self.login_win, text="TAQUERÍA PRO", font=("Segoe UI", 24, "bold"), bg="#111827", fg="#10b981").pack(pady=20)
        tk.Label(self.login_win, text="Ingrese su PIN de Empleado:", bg="#111827", fg="white", font=("Segoe UI", 12)).pack()

        self.pin_var = tk.StringVar()
        entry = tk.Label(self.login_win, textvariable=self.pin_var, font=("Courier", 30, "bold"), bg="#1f2937", fg="#10b981", width=10, relief="sunken")
        entry.pack(pady=20)
        
        pad_frame = tk.Frame(self.login_win, bg="#111827")
        pad_frame.pack()
        
        def add_digit(d):
            if len(self.pin_var.get()) < 4:
                self.pin_var.set(self.pin_var.get() + d)
                if len(self.pin_var.get()) == 4:
                    self.attempt_login()
        
        for i, row in enumerate([("1","2","3"), ("4","5","6"), ("7","8","9"), ("C","0","")]):
            for j, btn in enumerate(row):
                if btn == "": continue
                cmd = (lambda d=btn: self.pin_var.set("")) if btn == "C" else (lambda d=btn: add_digit(d))
                color = "#ef4444" if btn == "C" else "#374151"
                tk.Button(pad_frame, text=btn, font=("Segoe UI", 20, "bold"), bg=color, fg="white", width=4, height=1, command=cmd).grid(row=i, column=j, padx=10, pady=10)

    def attempt_login(self):
        pin = self.pin_var.get()
        user = db.one("SELECT * FROM users WHERE pin=?", (pin,))
        if user:
            self.current_user = dict(user)
            self.login_win.destroy()
            self.deiconify() # Muestra la ventana principal
            messagebox.showinfo("Bienvenido", f"Sesión iniciada: {user['username']}")
            logger.info(f"Usuario {user['username']} inició sesión con PIN.")
            
            # Refrescar pantallas
            if hasattr(self, 'refresh_tables'): self.refresh_tables()
            if hasattr(self, 'refresh_inventory'): self.refresh_inventory()
            if hasattr(self, 'refresh_users'): self.refresh_users()
            if hasattr(self, 'refresh_products'): self.refresh_products()
        else:
            messagebox.showerror("Error", "PIN Incorrecto")
            self.pin_var.set("")

    # --- LÓGICA DE INTERFAZ TÁCTIL ---
    def open_payment_window(self):
        """Ventana con botones grandes para pago rápido."""
        if not self.current_order_id:
            messagebox.showwarning("POS", "Seleccione una mesa primero")
            return

        win = Toplevel(self)
        win.title("Finalizar Venta")
        win.geometry("400x450")
        win.grab_set()

        import json
        try:
            with open("branding.json", "r", encoding="utf-8") as f:
                branding = json.load(f)
        except:
            branding = {}
        enable_loyalty = branding.get("enable_loyalty", True)

        tk.Label(win, text="MÉTODO DE PAGO", font=("Arial", 14, "bold")).pack(pady=20)
        
        self.customer_phone_var = tk.StringVar()
        if enable_loyalty:
            tk.Label(win, text="Número Teléfono (Billetera Puntos):", font=('Segoe UI', 12)).pack(pady=(10,0))
            tk.Entry(win, textvariable=self.customer_phone_var, font=('Segoe UI', 14), width=15).pack()

        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=20)
        
        ttk.Button(btn_frame, text="Efectivo", command=lambda: self.process_pay('efectivo', win)).grid(row=0, column=0, padx=5, pady=5)
        ttk.Button(btn_frame, text="Tarjeta", command=lambda: self.process_pay('tarjeta', win)).grid(row=0, column=1, padx=5, pady=5)
        
        if enable_loyalty:
            ttk.Button(btn_frame, text="Puntos Fidelidad", command=lambda: self.process_pay('puntos', win)).grid(row=0, column=2, padx=5, pady=5)
            
        ttk.Button(btn_frame, text="🎁 Canjear Vale/GiftCard", command=lambda: self.pay_with_giftcard(win)).grid(row=1, column=0, columnspan=3, pady=10)

    def pay_with_giftcard(self, window):
        v_id = simpledialog.askstring("Canjear Vale", "Escanee el código QR o digite el ID del Vale:", parent=window)
        if not v_id: return
        
        v = db.one("SELECT * FROM vouchers WHERE id=?", (v_id,))
        if not v:
            messagebox.showerror("Error", "El vale no existe.")
            return
        if v['is_redeemed']:
            messagebox.showerror("Error", "Este vale ya fue canjeado.")
            return
            
        db.execute("UPDATE vouchers SET is_redeemed=1 WHERE id=?", (v_id,))
        messagebox.showinfo("Éxito", f"Vale '{v['type']}' validado correctamente.")
        self.process_pay('giftcard', window)

    def process_pay(self, method, window):
        """Procesa el pago, asume inventario dinámico, y asigna puntos."""
        order = db.one("SELECT * FROM orders WHERE id=?", (self.current_order_id,))
        items = db.all("SELECT * FROM order_items WHERE order_id=?", (self.current_order_id,))
        
        # Billetera de Puntos
        phone = self.customer_phone_var.get()
        if phone:
            points_earned = int(order['total_cop'] / 100) # Gana 1% en puntos
            db.execute("INSERT INTO customers (phone, points) VALUES (?, ?) ON CONFLICT(phone) DO UPDATE SET points = points + ?", (phone, points_earned, points_earned))
            logger.info(f"Abonados {points_earned} puntos al cliente {phone}")
        
        success, msg = db.close_order_with_inventory(self.current_order_id, method)
        if success:
            # Save Branding
            import json
            branding_data = {
                "business_name": self.brand_name_var.get(),
                "theme_color": self.brand_color_var.get(),
                "branch_id": self.branch_id_var.get(),
                "master_server_url": self.master_url_var.get(),
                "enable_loyalty": self.enable_loyalty_var.get()
            }
            with open("branding.json", "w", encoding="utf-8") as f:
                json.dump(branding_data, f)
            
            self.title(f"{self.brand_name_var.get()} - {self.branch_id_var.get()} - POS")
            if order:
                write_ticket(self.current_order_id, str(order['table_number']), items, order['total_cop'], method)
            messagebox.showinfo("Éxito", f"Venta cerrada vía {method}\nTicket generado en carpeta 'tickets'.\nAjustes y Marca Blanca guardados correctamente.")
            logger.info(f"Orden {self.current_order_id} cerrada con {method}.")
            window.destroy()
            self.current_order_id = None
            self.refresh_tables()
            self.refresh_current_order()
        else:
            messagebox.showerror("Error", msg)

    def update_cfd(self, order_id, table_num, items, total):
        """Envía el estado actual del carrito a la Pantalla de Cliente."""
        try:
            import json, urllib.request
            data = json.dumps({"order_id": order_id, "table": table_num, "items": items, "total": total}).encode('utf-8')
            req = urllib.request.Request("http://localhost:8000/api/cfd_update", data=data, headers={'Content-Type': 'application/json', 'x-api-key': '123456'})
            urllib.request.urlopen(req, timeout=1)
        except Exception:
            pass # Falla silenciosa si la API está apagada

    def auto_refresh_kitchen(self):
        """Refresca la cocina automáticamente cada 30 segundos."""
        if hasattr(self, 'kitchen_tree'):
            self.refresh_kitchen()
        self.after(30000, self.auto_refresh_kitchen)
# --- CONSTRUCCIÓN DE PESTAÑAS ADMINISTRATIVAS ---
    def build_admin_tab(self):
        """Genera el Notebook superior para la administración."""
        nb = ttk.Notebook(self.admin_tab)
        nb.pack(fill='both', expand=True)
        
        self.users_panel = tk.Frame(nb, bg='white')
        self.products_panel = tk.Frame(nb, bg='white')
        self.inventory_panel = tk.Frame(nb, bg='white')
        self.promos_panel = tk.Frame(nb, bg='white')
        self.settings_panel = tk.Frame(nb, bg='white')
        
        nb.add(self.users_panel, text='Usuarios')
        nb.add(self.products_panel, text='Productos')
        nb.add(self.inventory_panel, text='Inventario')
        nb.add(self.promos_panel, text='QR / Promos')
        nb.add(self.settings_panel, text='Ajustes / Cierre')
        
        self.build_users_panel()
        self.build_products_panel()
        self.build_inventory_panel()
        self.build_promos_panel()
        self.build_settings_panel()

    # --- GESTIÓN DE USUARIOS (Lógica original recuperada) ---
    def build_users_panel(self):
        left = tk.Frame(self.users_panel, bg='white', padx=10, pady=10)
        left.pack(side='left', fill='y')
        right = tk.Frame(self.users_panel, bg='white', padx=10, pady=10)
        right.pack(side='left', fill='both', expand=True)
        
        self.users_list = tk.Listbox(left, width=35, height=25)
        self.users_list.pack()
        
        tk.Button(left, text='Refrescar', command=self.refresh_users).pack(fill='x', pady=3)
        tk.Button(left, text='Crear usuario', command=self.create_user).pack(fill='x', pady=3)
        tk.Button(left, text='Cambiar PIN cajero', command=self.change_pin).pack(fill='x', pady=3)
        
        self.user_info = tk.Text(right, height=20)
        self.user_info.pack(fill='both', expand=True)
        self.refresh_users()
        self.users_list.bind('<<ListboxSelect>>', lambda e: self.show_user_info())

    def refresh_users(self):
        self.users = db.all('SELECT * FROM users ORDER BY role, username')
        self.users_list.delete(0, 'end')
        for u in self.users:
            self.users_list.insert('end', f"{u['username']} | {u['role']} | {'Activo' if u['active'] else 'Inactivo'}")

    # --- GESTIÓN DE INVENTARIO (Con alertas de stock bajo) ---
    def build_inventory_panel(self):
        left = tk.Frame(self.inventory_panel, bg='white', padx=10, pady=10)
        left.pack(side='left', fill='y')
        right = tk.Frame(self.inventory_panel, bg='white', padx=10, pady=10)
        right.pack(side='left', fill='both', expand=True)
        
        self.inventory_list = tk.Listbox(left, width=40, height=25)
        self.inventory_list.pack()
        
        for txt, cmd in [('Refrescar', self.refresh_inventory), ('Agregar Insumo', self.add_inventory), ('Ajustar Stock', self.adjust_stock)]:
            tk.Button(left, text=txt, command=cmd).pack(fill='x', pady=3)
            
        self.inventory_text = tk.Text(right, height=20)
        self.inventory_text.pack(fill='both', expand=True)
        self.inventory_list.bind('<<ListboxSelect>>', lambda e: self.show_inventory_info())
        self.refresh_inventory()

    def refresh_inventory(self):
        self.inventory = db.all('SELECT * FROM inventory_items ORDER BY inventory_type, name')
        self.inventory_list.delete(0, 'end')
        for i in self.inventory:
            tag = '⚠️ COMPRAR' if i['stock_current'] <= i['stock_min'] else ''
            self.inventory_list.insert('end', f"{i['name']} | {i['stock_current']} {i['unit']} | {tag}")
    # --- GESTIÓN DE PRODUCTOS Y CATEGORÍAS ---
    def build_products_panel(self):
        left = tk.Frame(self.products_panel, bg='white', padx=10, pady=10)
        left.pack(side='left', fill='y')
        right = tk.Frame(self.products_panel, bg='white', padx=10, pady=10)
        right.pack(side='left', fill='both', expand=True)
        
        self.products_list = tk.Listbox(left, width=40, height=25)
        self.products_list.pack()
        
        for txt, cmd in [('Refrescar', self.refresh_products), ('Nuevo Producto', self.add_product), 
                         ('Editar', self.edit_product), ('Configurar Receta', self.manage_recipe)]:
            tk.Button(left, text=txt, command=cmd).pack(fill='x', pady=3)
            
        self.product_info = tk.Text(right, height=20)
        self.product_info.pack(fill='both', expand=True)
        self.products_list.bind('<<ListboxSelect>>', lambda e: self.show_product_info())
        self.refresh_products()

    def refresh_products(self):
        self.products = db.all('SELECT p.*, c.name category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.name')
        self.products_list.delete(0, 'end')
        for p in self.products:
            self.products_list.insert('end', f"{p['name']} | {cop(p['price_cop'])} | {'Activo' if p['active'] else 'Inactivo'}")

    def manage_recipe(self):
        """Vincula productos con insumos para el descuento automático."""
        p = self.selected_product()
        if not p: return
        inv = db.all('SELECT id, name FROM inventory_items ORDER BY name')
        choices = '\n'.join([f"ID {i['id']} - {i['name']}" for i in inv])
        item_id = simpledialog.askinteger('Receta', f'ID de insumo:\n{choices}', parent=self)
        if not item_id: return
        qty = simpledialog.askinteger('Receta', 'Cantidad que consume (ej: 90 para gramos)', minvalue=1, parent=self)
        if not qty: return
        db.execute('INSERT OR REPLACE INTO recipe_items (product_id, inventory_item_id, qty_needed) VALUES (?,?,?)', (p['id'], item_id, qty))
        messagebox.showinfo('Receta', 'Ingrediente vinculado')

    # --- QR Y MENÚ DIGITAL ---
    def build_promos_panel(self):
        left = tk.Frame(self.promos_panel, bg='white', padx=10, pady=10)
        left.pack(side='left', fill='y')
        right = tk.Frame(self.promos_panel, bg='white', padx=10, pady=10)
        right.pack(side='left', fill='both', expand=True)
        
        tk.Button(left, text='Generar QRs para Mesas', command=self.generate_qrs, bg='#10b981', fg='white', font=('Arial', 12, 'bold')).pack(fill='x', pady=10)
        tk.Button(left, text='🎁 Crear Gift Card / Donación', command=self.open_voucher_generator, bg='#8b5cf6', fg='white', font=('Arial', 12, 'bold')).pack(fill='x', pady=10)
        
        self.qr_info = tk.Text(right, height=20, font=("Arial", 12))
        self.qr_info.pack(fill='both', expand=True)
        self.qr_info.insert('end', "Administrador de Vales y QRs.\nSe guardarán en la carpeta 'backend/qrs'.\n")

    def open_voucher_generator(self):
        import uuid, qrcode, os
        from datetime import datetime
        
        win = Toplevel(self)
        win.title("Generador de Vales y Gift Cards")
        win.geometry("400x350")
        win.grab_set()
        
        tk.Label(win, text="Tipo de Vale:", font=('Arial', 10, 'bold')).pack(pady=5)
        type_var = tk.StringVar(value="giftcard")
        ttk.Combobox(win, textvariable=type_var, values=["giftcard", "donacion"], state="readonly").pack()
        
        tk.Label(win, text="Valor en Dinero COP (Para GiftCard):").pack(pady=5)
        val_var = tk.StringVar(value="50000")
        tk.Entry(win, textvariable=val_var).pack()
        
        tk.Label(win, text="Teléfono / Cédula del Beneficiario:").pack(pady=5)
        id_var = tk.StringVar()
        tk.Entry(win, textvariable=id_var).pack()
        
        def save():
            v_id = str(uuid.uuid4())[:8].upper()
            t = type_var.get()
            val = int(val_var.get() or 0)
            ident = id_var.get()
            
            db.execute("INSERT INTO vouchers (id, type, value_cop, items_json, identifier, is_redeemed, created_at) VALUES (?,?,?,?,?,0,?)",
                       (v_id, t, val, "[]", ident, datetime.now().isoformat()))
            
            qr_dir = os.path.join(os.path.dirname(__file__), "qrs")
            os.makedirs(qr_dir, exist_ok=True)
            img = qrcode.make(v_id)
            path = os.path.join(qr_dir, f"Vale_{v_id}.png")
            img.save(path)
            
            self.qr_info.insert('end', f"Generado Vale: {v_id} -> {path}\n")
            messagebox.showinfo("Vale Generado", f"Vale: {v_id}\n\nSe ha generado una imagen con el Código QR en la carpeta 'qrs'. Puedes enviársela al cliente por WhatsApp o imprimirla.")
            win.destroy()
            
        tk.Button(win, text="Generar y Crear QR", command=save, bg="#10b981", fg="white", font=('Arial', 12, 'bold')).pack(pady=20)

    def generate_qrs(self):
        """Genera QRs para todas las mesas."""
        try:
            import qrcode
            import os
            from app.db import db
            qr_dir = os.path.join(os.path.dirname(__file__), "qrs")
            os.makedirs(qr_dir, exist_ok=True)
            mesas = db.all('SELECT * FROM tables')
            
            self.qr_info.delete("1.0", "end")
            for m in mesas:
                url = f"http://localhost:8000/customer.html?table={m['id']}" # Cambiar localhost por IP real
                img = qrcode.make(url)
                img.save(os.path.join(qr_dir, f"mesa_{m['table_number']}.png"))
                self.qr_info.insert('end', f"Generado: mesa_{m['table_number']}.png\n")
            messagebox.showinfo("Éxito", f"QRs generados en {qr_dir}")
        except ImportError:
            messagebox.showerror("Error", "La librería qrcode no está instalada.")
        except Exception as e:
            messagebox.showerror("Error", f"Error generando QRs: {e}")

    # --- AJUSTES Y REPORTE DE CIERRE ---
    def build_settings_panel(self):
        frame = tk.Frame(self.settings_panel, bg='white', padx=10, pady=10)
        frame.pack(fill='both', expand=True)
        s = db.one('SELECT * FROM settings WHERE id=1')
        self.setting_vars = {}
        fields = [('business_name','Negocio'), ('smtp_host','SMTP Host'), ('smtp_port','Puerto'), 
                  ('smtp_username','Usuario'), ('smtp_password','Clave'), ('report_to','Enviar reporte a')]
        
        for key, label in fields:
            tk.Label(frame, text=label, bg='white').pack(anchor='w')
            var = tk.StringVar(value=str(s[key] or ''))
            self.setting_vars[key] = var
            tk.Entry(frame, textvariable=var, width=50).pack(anchor='w', pady=(0,6))

        import json
        try:
            with open("branding.json", "r", encoding="utf-8") as f:
                branding = json.load(f)
        except:
            branding = {"business_name": "Restaurante", "theme_color": "#10b981"}

        self.brand_name_var = tk.StringVar(value=branding.get("business_name", "Restaurante"))
        self.brand_color_var = tk.StringVar(value=branding.get("theme_color", "#10b981"))
        self.branch_id_var = tk.StringVar(value=branding.get("branch_id", "SUC-01"))
        self.master_url_var = tk.StringVar(value=branding.get("master_server_url", ""))
        self.enable_loyalty_var = tk.BooleanVar(value=branding.get("enable_loyalty", True))
        
        tk.Label(frame, text="Configuración de Fidelización (Clientes)", font=('Segoe UI', 12, 'bold'), fg='#8b5cf6').pack(anchor='w', pady=(15,5))
        tk.Checkbutton(frame, text="Habilitar Billetera de Puntos y Recompensas", variable=self.enable_loyalty_var, font=('Segoe UI', 10)).pack(anchor='w', pady=(0,10))

        tk.Label(frame, text="Configuración de Sincronización (Multi-Sucursal)", font=('Segoe UI', 12, 'bold'), fg='#2563eb').pack(anchor='w', pady=(15,5))
        
        tk.Label(frame, text="ID de Sucursal (Ej: SUC-NORTE):", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Entry(frame, textvariable=self.branch_id_var, width=50).pack(anchor='w', pady=(0,6))
        
        tk.Label(frame, text="URL del Servidor Maestro en la Nube (Opcional):", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Entry(frame, textvariable=self.master_url_var, width=50).pack(anchor='w', pady=(0,15))

        tk.Label(frame, text="Marca Blanca - Nombre del Negocio:", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Entry(frame, textvariable=self.brand_name_var, width=50).pack(anchor='w', pady=(0,6))
        
        tk.Label(frame, text="Marca Blanca - Color Temático (HEX):", font=('Segoe UI', 10, 'bold')).pack(anchor='w')
        tk.Entry(frame, textvariable=self.brand_color_var, width=50).pack(anchor='w', pady=(0,6))

        tk.Button(frame, text='Guardar Ajustes', command=self.save_settings, bg='#2563eb', fg='white').pack(pady=10)
        
        self.report_preview = tk.Text(frame, height=10)
        self.report_preview.pack(fill='x', pady=10)

    def execute_blind_close(self):
        """Cierre Ciego: Obliga a contar efectivo antes de ver el reporte del sistema."""
        from tkinter.simpledialog import askfloat
        from app.db import db
        from datetime import date
        
        efectivo_caja = askfloat("Cierre Ciego de Caja", "Ingrese la cantidad EXACTA de efectivo contada en la gaveta:", parent=self)
        if efectivo_caja is None: return
        
        try:
            today = date.today().isoformat()
            rows = db.all("SELECT total_cop, payment_method FROM orders WHERE status='closed' AND substr(closed_at,1,10)=?", (today,))
            
            efectivo_sistema = sum(r['total_cop'] for r in rows if r['payment_method'] == 'efectivo')
            diferencia = efectivo_caja - efectivo_sistema
            
            msg = f"Efectivo Registrado: ${efectivo_sistema:,.0f}\n"
            msg += f"Efectivo Real: ${efectivo_caja:,.0f}\n"
            msg += "-"*20 + "\n"
            if diferencia < 0:
                msg += f"FALTANTE: ${abs(diferencia):,.0f}"
                messagebox.showerror("ALERTA DE DESCUADRE", msg)
            elif diferencia > 0:
                msg += f"SOBRANTE: ${diferencia:,.0f}"
                messagebox.showwarning("SOBRANTE EN CAJA", msg)
            else:
                msg += "¡CAJA CUADRADA PERFECTAMENTE!"
                messagebox.showinfo("Cierre Exitoso", msg)
                
            db.execute("INSERT INTO audit_log (username, action, details) VALUES (?,?,?)", (self.current_user['username'], 'cierre_ciego', msg.replace('\n', ' ')))
            logger.info(f"Cierre Ciego realizado por {self.current_user['username']}. Diferencia: {diferencia}")
        except Exception as e:
            logger.error(f"Error en cierre ciego: {e}")
            messagebox.showerror("Error", f"Error en cierre: {e}")

        def _send():
            ok, msg = send_email(s['smtp_host'], s['smtp_port'], s['smtp_username'], s['smtp_password'], 
                                 s['report_from'], s['report_to'], "Cierre de Caja", body)
            if ok:
                self.after(0, lambda: messagebox.showinfo('Reporte', 'Enviado con éxito'))
            else:
                self.after(0, lambda: messagebox.showerror('Error', msg))
                
        threading.Thread(target=_send, daemon=True).start()
        messagebox.showinfo('Reporte', 'Enviando reporte de cierre en segundo plano...')

if __name__ == '__main__':
    App().mainloop()