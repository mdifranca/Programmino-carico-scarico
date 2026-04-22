const state = {
  products: [],
  movements: [],
  importRows: [],
  currentEditId: null,
};

const els = {
  heroStats: document.getElementById("heroStats"),
  productForm: document.getElementById("productForm"),
  movementForm: document.getElementById("movementForm"),
  movementProduct: document.getElementById("movementProduct"),
  inventoryTableWrap: document.getElementById("inventoryTableWrap"),
  historyTableWrap: document.getElementById("historyTableWrap"),
  searchProducts: document.getElementById("searchProducts"),
  importFile: document.getElementById("importFile"),
  importText: document.getElementById("importText"),
  importRowsWrap: document.getElementById("importRows"),
  importMode: document.getElementById("importMode"),
  importRowTemplate: document.getElementById("importRowTemplate"),
  exportProducts: document.getElementById("exportProducts"),
  exportMovements: document.getElementById("exportMovements"),
  exportBackup: document.getElementById("exportBackup"),
  networkLink: document.getElementById("networkLink"),
  importStatus: document.getElementById("importStatus"),
};

boot();

async function boot() {
  bindEvents();
  await refreshData();
  await loadServerInfo();
}

function bindEvents() {
  els.productForm.addEventListener("submit", onSaveProduct);
  els.movementForm.addEventListener("submit", onSaveMovement);
  els.searchProducts.addEventListener("input", renderInventoryTable);
  document.getElementById("parseImport").addEventListener("click", onParseImport);
  document.getElementById("applyImport").addEventListener("click", onApplyImport);
  document.getElementById("clearImport").addEventListener("click", clearImportArea);
  document.getElementById("productCategory").addEventListener("change", onCategoryChange);
}

async function refreshData() {
  const [products, movements] = await Promise.all([
    api("/api/products"),
    api("/api/movements?limit=25"),
  ]);

  state.products = products;
  state.movements = movements;
  renderAll();
}

async function loadServerInfo() {
  const info = await api("/api/info");
  els.exportProducts.href = "/api/export/products.csv";
  els.exportMovements.href = "/api/export/movements.csv";
  els.exportBackup.href = "/api/export/backup.json";
  const publicLink = info.public_url || info.network_url || info.local_url;
  els.networkLink.textContent = publicLink;
  els.networkLink.href = publicLink;
}

function renderAll() {
  renderStats();
  renderProductOptions();
  renderInventoryTable();
  renderHistoryTable();
}

function renderStats() {
  const totalProducts = state.products.length;
  const totalUnits = state.products.reduce((sum, product) => sum + Number(product.quantity), 0);
  const alerts = state.products.filter((product) => Number(product.quantity) <= Number(product.alert)).length;

  els.heroStats.innerHTML = `
    <div class="stat">
      <span>Prodotti gestiti</span>
      <strong>${totalProducts}</strong>
    </div>
    <div class="stat">
      <span>Unita totali</span>
      <strong>${formatNumber(totalUnits)}</strong>
    </div>
    <div class="stat">
      <span>Da riordinare</span>
      <strong>${alerts}</strong>
    </div>
  `;
}

function renderProductOptions() {
  if (!state.products.length) {
    els.movementProduct.innerHTML = `<option value="">Inserisci prima un prodotto</option>`;
    return;
  }

  els.movementProduct.innerHTML = state.products
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name, "it"))
    .map((product) => `<option value="${product.id}">${escapeHtml(product.name)}</option>`)
    .join("");
}

function renderInventoryTable() {
  const query = els.searchProducts.value.trim().toLowerCase();
  const products = state.products
    .filter((product) => product.name.toLowerCase().includes(query))
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name, "it"));

  if (!products.length) {
    els.inventoryTableWrap.innerHTML = `<div class="empty-table">Nessun prodotto trovato.</div>`;
    return;
  }

  els.inventoryTableWrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Prodotto</th>
          <th>Categoria</th>
          <th>Giacenza</th>
          <th>Alert</th>
          <th>Cassa</th>
          <th>Stato</th>
          <th>Azioni</th>
        </tr>
      </thead>
      <tbody>
        ${products
          .map((product) => {
            const alertState = Number(product.quantity) <= Number(product.alert);
            return `
              <tr>
                <td>${escapeHtml(product.name)}<br><span class="muted">${escapeHtml(product.unit)}</span></td>
                <td>${escapeHtml(product.category)}</td>
                <td>${formatNumber(product.quantity)}</td>
                <td>${formatNumber(product.alert)}</td>
                <td>${formatNumber(product.case_size)}</td>
                <td><span class="pill ${alertState ? "alert" : "good"}">${alertState ? "Riordino" : "OK"}</span></td>
                <td class="actions-cell">
                  <button class="ghost" type="button" onclick="editProduct(${product.id})">Modifica</button>
                  <button class="ghost" type="button" onclick="deleteProduct(${product.id})">Elimina</button>
                </td>
              </tr>
            `;
          })
          .join("")}
      </tbody>
    </table>
  `;
}

function renderHistoryTable() {
  if (!state.movements.length) {
    els.historyTableWrap.innerHTML = `<div class="empty-table">Ancora nessun movimento registrato.</div>`;
    return;
  }

  els.historyTableWrap.innerHTML = `
    <table>
      <thead>
        <tr>
          <th>Data</th>
          <th>Prodotto</th>
          <th>Tipo</th>
          <th>Quantita</th>
          <th>Origine</th>
          <th>Nota</th>
        </tr>
      </thead>
      <tbody>
        ${state.movements
          .map(
            (movement) => `
              <tr>
                <td>${new Date(movement.created_at).toLocaleString("it-IT")}</td>
                <td>${escapeHtml(movement.product_name)}</td>
                <td><span class="pill ${movement.type}">${movement.type === "load" ? "Carico" : "Scarico"}</span></td>
                <td>${formatNumber(movement.quantity)}</td>
                <td>${escapeHtml(movement.source || "manuale")}</td>
                <td>${escapeHtml(movement.note || "-")}</td>
              </tr>
            `
          )
          .join("")}
      </tbody>
    </table>
  `;
}

function renderImportRows() {
  if (!state.importRows.length) {
    els.importRowsWrap.className = "import-rows empty-state";
    els.importRowsWrap.textContent = "Nessuna riga analizzata.";
    return;
  }

  els.importRowsWrap.className = "import-rows";
  els.importRowsWrap.innerHTML = "";

  state.importRows.forEach((row, index) => {
    const node = els.importRowTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".import-product").value = row.product_name;
    node.querySelector(".import-qty").value = row.base_quantity;
    node.querySelector(".import-meta").textContent = `${row.detected_unit_label} x${formatNumber(row.multiplier)}${row.category ? ` • ${row.category}` : ""}`;
    node.querySelector(".remove-import-row").addEventListener("click", () => {
      state.importRows.splice(index, 1);
      renderImportRows();
    });
    els.importRowsWrap.appendChild(node);
  });
}

async function onSaveProduct(event) {
  event.preventDefault();

  const payload = {
    name: document.getElementById("productName").value.trim(),
    quantity: parseNumber(document.getElementById("productQty").value),
    alert: parseNumber(document.getElementById("productAlert").value),
    unit: document.getElementById("productUnit").value.trim() || "bottiglie",
    category: document.getElementById("productCategory").value,
    case_size: parseNumber(document.getElementById("productCaseSize").value),
  };

  if (!payload.name) return;

  if (state.currentEditId) {
    await api(`/api/products/${state.currentEditId}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  } else {
    await api("/api/products", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  resetProductForm();
  await refreshData();
}

async function onSaveMovement(event) {
  event.preventDefault();
  const payload = {
    product_id: Number(els.movementProduct.value),
    type: document.getElementById("movementType").value,
    quantity: parseNumber(document.getElementById("movementQty").value),
    note: document.getElementById("movementNote").value.trim(),
    source: "manuale",
  };

  if (!payload.product_id || payload.quantity <= 0) return;

  await api("/api/movements", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  els.movementForm.reset();
  await refreshData();
}

async function onParseImport() {
  const text = els.importText.value.trim();
  const file = els.importFile.files[0];

  els.importStatus.textContent = "Analisi in corso...";

  const payload = {
    mode: els.importMode.value,
    text,
    file_name: file ? file.name : null,
    file_content_base64: file ? await toBase64(file) : null,
  };

  const result = await api("/api/import/parse", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  state.importRows = result.rows;
  renderImportRows();
  els.importStatus.textContent = result.message;
}

async function onApplyImport() {
  const rows = Array.from(els.importRowsWrap.querySelectorAll(".import-row")).map((row) => ({
    product_name: row.querySelector(".import-product").value.trim(),
    base_quantity: parseNumber(row.querySelector(".import-qty").value),
  })).filter((row) => row.product_name && row.base_quantity > 0);

  if (!rows.length) return;

  await api("/api/import/apply", {
    method: "POST",
    body: JSON.stringify({
      mode: els.importMode.value,
      rows,
    }),
  });

  clearImportArea();
  await refreshData();
}

function clearImportArea() {
  state.importRows = [];
  els.importText.value = "";
  els.importFile.value = "";
  els.importStatus.textContent = "Nessun documento analizzato.";
  renderImportRows();
}

function onCategoryChange(event) {
  const field = document.getElementById("productCaseSize");
  const value = event.target.value;
  if (value === "soft") field.value = "24";
  if (value === "alcol") field.value = "6";
}

window.editProduct = (productId) => {
  const product = state.products.find((item) => Number(item.id) === Number(productId));
  if (!product) return;

  state.currentEditId = product.id;
  document.getElementById("productName").value = product.name;
  document.getElementById("productQty").value = product.quantity;
  document.getElementById("productAlert").value = product.alert;
  document.getElementById("productUnit").value = product.unit;
  document.getElementById("productCategory").value = product.category;
  document.getElementById("productCaseSize").value = product.case_size;
  document.getElementById("productSubmitLabel").textContent = "Aggiorna prodotto";
  window.scrollTo({ top: 0, behavior: "smooth" });
};

window.deleteProduct = async (productId) => {
  const product = state.products.find((item) => Number(item.id) === Number(productId));
  if (!product) return;

  const confirmed = window.confirm(`Eliminare "${product.name}" dal magazzino?`);
  if (!confirmed) return;

  await api(`/api/products/${product.id}`, {
    method: "DELETE",
  });

  await refreshData();
};

function resetProductForm() {
  state.currentEditId = null;
  els.productForm.reset();
  document.getElementById("productQty").value = "0";
  document.getElementById("productAlert").value = "0";
  document.getElementById("productCaseSize").value = "6";
  document.getElementById("productCategory").value = "alcol";
  document.getElementById("productUnit").value = "bottiglie";
  document.getElementById("productSubmitLabel").textContent = "Salva prodotto";
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "Richiesta non riuscita");
  }

  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result);
      resolve(result.split(",")[1]);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function parseNumber(value) {
  const normalized = String(value).replace(",", ".").trim();
  return Number.parseFloat(normalized) || 0;
}

function formatNumber(value) {
  return new Intl.NumberFormat("it-IT", {
    minimumFractionDigits: Number.isInteger(Number(value)) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
