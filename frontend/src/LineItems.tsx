import { useCallback, useEffect, useState } from "react";
import { api, inr } from "./api";
import type { Paginated } from "./types";

interface Product { id: number; name: string; unit_price: string; tax_rate: string }
interface Item {
  id: number; product: number; product_name: string; quantity: string;
  unit_price: string; discount_pct: string; subtotal: string;
}

/** PR-2: line items with catalogue prices; auto-sum toggle drives deal value. */
export default function LineItems({ dealId, valueAuto, onChanged }: {
  dealId: number;
  valueAuto: boolean;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [auto, setAuto] = useState(valueAuto);

  const load = useCallback(async () => {
    const r = await api<{ items: Item[]; value_auto: boolean }>(
      `/deals/${dealId}/line_items/`);
    setItems(r.items);
    setAuto(r.value_auto);
  }, [dealId]);

  useEffect(() => {
    void load();
    void api<Paginated<Product>>("/products/?active=1").then((d) => setProducts(d.results));
  }, [load]);

  const add = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (!f.get("product")) return;
    await api(`/deals/${dealId}/line_items/`, { method: "POST", body: {
      product: Number(f.get("product")),
      quantity: (f.get("qty") as string) || "1",
      discount_pct: (f.get("disc") as string) || "0",
    } });
    e.currentTarget.reset();
    void load();
    onChanged();
  };

  const remove = async (id: number) => {
    await api(`/deals/${dealId}/line_items/${id}/`, { method: "DELETE" });
    void load();
    onChanged();
  };

  const toggleAuto = async (checked: boolean) => {
    setAuto(checked);
    await api(`/deals/${dealId}/`, { method: "PATCH", body: { value_auto: checked } });
    onChanged();
  };

  return (
    <div style={{ margin: "14px 0" }}>
      <h3 style={{ fontSize: 14, margin: "0 0 8px" }}>
        Products{" "}
        <label style={{ fontWeight: 400, color: "var(--muted)", fontSize: 12 }}>
          <input type="checkbox" checked={auto}
            onChange={(e) => void toggleAuto(e.target.checked)} /> deal value = Σ items
        </label>
      </h3>
      {items.map((it) => (
        <div key={it.id} style={{ display: "flex", justifyContent: "space-between",
          fontSize: 13, padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
          <span>{it.product_name} × {Number(it.quantity)}
            {Number(it.discount_pct) > 0 ? ` (−${Number(it.discount_pct)}%)` : ""}</span>
          <span>{inr(it.subtotal)}{" "}
            <a href="#" style={{ color: "var(--rot)" }}
              onClick={(e) => { e.preventDefault(); void remove(it.id); }}>✗</a></span>
        </div>
      ))}
      <form onSubmit={add} style={{ display: "flex", gap: 6, marginTop: 8 }}>
        <select name="product" defaultValue="" style={{ flex: 1 }}>
          <option value="" disabled>Add product…</option>
          {products.map((p) => (
            <option key={p.id} value={p.id}>{p.name} ({inr(p.unit_price)})</option>
          ))}
        </select>
        <input name="qty" type="number" step="any" placeholder="Qty" style={{ width: 70 }} />
        <input name="disc" type="number" step="any" placeholder="−%" style={{ width: 60 }} />
        <button className="ghost">Add</button>
      </form>
    </div>
  );
}
