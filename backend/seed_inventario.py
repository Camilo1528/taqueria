"""Carga los mínimos y máximos de inventario definidos por la administración.

Uso (desde la carpeta backend):  python seed_inventario.py
Es seguro ejecutarlo varias veces: si el ítem ya existe (mismo nombre),
solo actualiza mínimo y máximo; no toca el stock actual.
"""
from app.db import db

# (nombre, mínimo, máximo) — todas las cantidades en unidades (porciones)
ITEMS = [
    ("Carne al pastor x 35 gr", 60, 150),
    ("Carne al pastor x 70 gr", 40, 100),
    ("Carne hamburguesa x 120 gr", 10, 45),
    ("Carne arrachera x 35 gr", 60, 130),
    ("Carne arrachera x 70 gr", 20, 80),
    ("Carne cochinita pibil x 35 gr", 60, 160),
    ("Carne cochinita pibil x 70 gr", 50, 150),
    ("Pollo desmechado x 70 gr", 30, 60),
    ("Carne de chorizo x 35 gr", 10, 30),
    ("Morrillo x 70 gr", 30, 80),
    ("Pollo tinga x 80 gr", 15, 60),
    ("Lengua de res x 35 gr", 20, 60),
    ("Pollo apanado x 35 gr", 15, 60),
    ("Camarón x 3 und", 15, 45),
    ("Mix de queso x 60 gr", 24, 72),
    ("Mix de queso x 80 gr", 10, 40),
    ("Pan de hamburguesa x 1 und", 15, 45),
    ("Doritos x 1 und", 5, 12),
    ("Sour cream x 700 gr", 4, 12),
]


def main(clean_others: bool = True) -> None:
    allowed_names = [name.lower() for name, _, _ in ITEMS]

    if clean_others:
        placeholders = ",".join("?" for _ in allowed_names)
        db.execute(
            f"DELETE FROM recipe_items WHERE inventory_item_id IN (SELECT id FROM inventory_items WHERE lower(name) NOT IN ({placeholders}))",
            tuple(allowed_names),
        )
        db.execute(
            f"DELETE FROM inventory_items WHERE lower(name) NOT IN ({placeholders})",
            tuple(allowed_names),
        )
        print("Eliminados ítems antiguos de inventario que no están en la lista oficial.")

    creados = actualizados = 0
    for name, mn, mx in ITEMS:
        row = db.one("SELECT id FROM inventory_items WHERE lower(name)=lower(?)", (name,))
        if row:
            db.execute("UPDATE inventory_items SET name=?, stock_min=?, stock_max=?, unit='und' WHERE id=?", (name, mn, mx, row["id"]))
            actualizados += 1
        else:
            db.execute(
                "INSERT INTO inventory_items (name, stock_current, stock_min, stock_max, unit, inventory_type) "
                "VALUES (?, 0, ?, ?, 'und', 'ingrediente')",
                (name, mn, mx),
            )
            creados += 1
    print(f"Inventario listo: {creados} creados, {actualizados} actualizados.")


if __name__ == "__main__":
    main()
