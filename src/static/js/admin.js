// src/static/js/admin.js

/**
 * Administrative console client script for BansiGo:
 * - Tab switching & deep linking
 * - Product search, filtering & pagination
 * - Add/Edit Product & Size Variant creation workflows
 * - Interactive & Arrangeable Product Image Gallery
 * - Bulk CSV import & export
 * - System actors regulation with modal confirmations
 * - Two-Factor Authentication (2FA) email OTP lifecycle
 * - Authentication & Security Governance policy updates
 */

document.addEventListener('DOMContentLoaded', function () {
  const BASE_URL = window.ADMIN_BASE_URL || '/console-hq/admin';

  // -------------------------------------------------------------------------
  // 1. Navigation / Tab Switching
  // -------------------------------------------------------------------------
  const navItems = document.querySelectorAll('.admin-nav-item[data-tab]');
  const tabPanes = document.querySelectorAll('.admin-tab-pane');
  const sectionTitleEl = document.getElementById('adminSectionTitle');

  function switchTab(tabId) {
    navItems.forEach(item => {
      if (item.getAttribute('data-tab') === tabId) {
        item.classList.add('active');
        if (sectionTitleEl) {
          sectionTitleEl.textContent = item.querySelector('span')?.textContent || 'Dashboard';
        }
      } else {
        item.classList.remove('active');
      }
    });

    tabPanes.forEach(pane => {
      if (pane.id === tabId + 'Tab') {
        pane.classList.add('active');
      } else {
        pane.classList.remove('active');
      }
    });

    window.location.hash = tabId;
  }

  window.switchAdminTab = function (tabId) {
    const nav = document.querySelector(`.admin-nav-item[data-tab="${tabId}"]`);
    if (nav) {
      nav.click();
    } else {
      switchTab(tabId);
    }
  };

  navItems.forEach(item => {
    item.addEventListener('click', function (e) {
      e.preventDefault();
      const tabId = this.getAttribute('data-tab');
      switchTab(tabId);
    });
  });

  const initialTab = window.location.hash ? window.location.hash.substring(1) : 'overview';
  const targetNavItem = document.querySelector(`.admin-nav-item[data-tab="${initialTab}"]`);
  if (targetNavItem) {
    switchTab(initialTab);
  }

  // -------------------------------------------------------------------------
  // 2. Generic Confirmation Modal Dispatcher
  // -------------------------------------------------------------------------
  const confirmationModalEl = document.getElementById('confirmationModal');
  const confirmProceedBtn = document.getElementById('confirmProceedBtn');
  const confirmCancelBtn = document.getElementById('confirmCancelBtn');
  const confirmModalTitle = document.getElementById('confirmModalTitle');
  const confirmModalMessage = document.getElementById('confirmModalMessage');
  let currentConfirmHandler = null;
  let currentCancelHandler = null;

  window.confirmAction = function ({
    title = 'Confirm Action',
    message = 'Are you sure you want to proceed?',
    confirmBtnText = 'Confirm & Proceed',
    confirmBtnClass = 'btn-bansi-red',
    onConfirm = null,
    onCancel = null,
  }) {
    if (!confirmationModalEl) {
      if (confirm(message)) {
        if (onConfirm) onConfirm();
      } else {
        if (onCancel) onCancel();
      }
      return;
    }

    if (confirmModalTitle) confirmModalTitle.textContent = title;
    if (confirmModalMessage) confirmModalMessage.textContent = message;

    if (confirmProceedBtn) {
      confirmProceedBtn.textContent = confirmBtnText;
      confirmProceedBtn.className = `btn btn-sm px-3 ${confirmBtnClass}`;
    }

    currentConfirmHandler = onConfirm;
    currentCancelHandler = onCancel;

    const modal = bootstrap.Modal.getOrCreateInstance(confirmationModalEl);
    modal.show();
  };

  if (confirmProceedBtn) {
    confirmProceedBtn.addEventListener('click', function () {
      const modal = bootstrap.Modal.getInstance(confirmationModalEl);
      if (modal) modal.hide();
      if (typeof currentConfirmHandler === 'function') {
        currentConfirmHandler();
      }
      currentConfirmHandler = null;
      currentCancelHandler = null;
    });
  }

  if (confirmationModalEl) {
    confirmationModalEl.addEventListener('hidden.bs.modal', function () {
      if (typeof currentCancelHandler === 'function') {
        currentCancelHandler();
      }
      currentConfirmHandler = null;
      currentCancelHandler = null;
    });
  }

  // -------------------------------------------------------------------------
  // 3. Product Search & Filter
  // -------------------------------------------------------------------------
  const productSearchInput = document.getElementById('productSearchInput');
  const categoryFilter = document.getElementById('categoryFilter');
  const stockFilter = document.getElementById('stockFilter');
  const productRows = document.querySelectorAll('.product-table-row');

  function filterProducts() {
    const query = (productSearchInput?.value || '').toLowerCase().trim();
    const catVal = (categoryFilter?.value || '').toLowerCase();
    const stockVal = stockFilter?.value || 'all';

    productRows.forEach(row => {
      const name = (row.getAttribute('data-name') || '').toLowerCase();
      const sku = (row.getAttribute('data-sku') || '').toLowerCase();
      const barcode = (row.getAttribute('data-barcode') || '').toLowerCase();
      const category = (row.getAttribute('data-category') || '').toLowerCase();
      const available = parseFloat(row.getAttribute('data-available') || '0');
      const isLow = row.getAttribute('data-low-stock') === 'true';

      const matchesQuery = !query || name.includes(query) || sku.includes(query) || barcode.includes(query);
      const matchesCategory = !catVal || category === catVal;

      let matchesStock = true;
      if (stockVal === 'low') matchesStock = isLow;
      else if (stockVal === 'out') matchesStock = available <= 0;
      else if (stockVal === 'in') matchesStock = available > 0;

      if (matchesQuery && matchesCategory && matchesStock) {
        row.style.display = '';
      } else {
        row.style.display = 'none';
      }
    });
  }

  if (productSearchInput) productSearchInput.addEventListener('input', filterProducts);
  if (categoryFilter) categoryFilter.addEventListener('change', filterProducts);
  if (stockFilter) stockFilter.addEventListener('change', filterProducts);

  // -------------------------------------------------------------------------
  // 4. Arrangeable & Previewable Product Image Gallery Manager
  // -------------------------------------------------------------------------
  window.productGalleryState = [];

  const galleryPreviewContainer = document.getElementById('galleryPreviewContainer');
  const galleryCountBadge = document.getElementById('galleryCountBadge');
  const modalGalleryImagesInput = document.getElementById('modalGalleryImages');
  const modalImageUrlInput = document.getElementById('modalImageUrl');
  const newImageUrlInput = document.getElementById('newImageUrlInput');
  const addImageUrlBtn = document.getElementById('addImageUrlBtn');

  function syncGalleryInputs() {
    if (modalGalleryImagesInput) {
      modalGalleryImagesInput.value = JSON.stringify(window.productGalleryState);
    }
    if (modalImageUrlInput) {
      modalImageUrlInput.value = window.productGalleryState[0] || '';
    }
    if (galleryCountBadge) {
      const count = window.productGalleryState.length;
      galleryCountBadge.textContent = `${count} Image${count === 1 ? '' : 's'}`;
    }
  }

  window.renderProductGallery = function () {
    syncGalleryInputs();
    if (!galleryPreviewContainer) return;

    if (window.productGalleryState.length === 0) {
      galleryPreviewContainer.innerHTML = `
        <div class="text-muted small py-3 text-center w-100" id="galleryEmptyMessage">
          <i class="ri-image-add-line fs-3 d-block text-secondary mb-1"></i>
          No images in gallery yet. Enter an image URL above to build product media.
        </div>
      `;
      return;
    }

    let html = '';
    window.productGalleryState.forEach((imgUrl, index) => {
      const isPrimary = index === 0;
      html += `
        <div class="product-gallery-item position-relative border rounded p-1 bg-light d-flex flex-column align-items-center"
             style="width: 120px; transition: transform 0.15s ease;" data-index="${index}">
          ${isPrimary ? '<span class="badge bg-danger position-absolute top-0 start-0 m-1" style="font-size: 0.65rem; z-index: 2;">Cover</span>' : ''}
          <div class="w-100 bg-white rounded overflow-hidden mb-1 d-flex align-items-center justify-content-center border" style="height: 85px;">
            <img src="${imgUrl}" alt="Product Preview" class="w-100 h-100 object-fit-cover"
                 onerror="this.onerror=null; this.src='https://placehold.co/120x85?text=Invalid+Image';">
          </div>
          <div class="d-flex justify-content-between align-items-center w-100 px-1">
            <button type="button" class="btn btn-xs btn-outline-secondary py-0 px-1" onclick="moveGalleryImage(${index}, -1)"
                    ${index === 0 ? 'disabled' : ''} title="Move Earlier" aria-label="Move Earlier">
              <i class="ri-arrow-left-s-line"></i>
            </button>
            ${!isPrimary ? `
              <button type="button" class="btn btn-xs btn-outline-warning py-0 px-1" onclick="setGalleryPrimary(${index})"
                      title="Set as Main Cover" aria-label="Set as Main Cover">
                <i class="ri-star-line"></i>
              </button>
            ` : ''}
            <button type="button" class="btn btn-xs btn-outline-danger py-0 px-1" onclick="removeGalleryImage(${index})"
                    title="Remove Image" aria-label="Remove Image">
              <i class="ri-delete-bin-line"></i>
            </button>
            <button type="button" class="btn btn-xs btn-outline-secondary py-0 px-1" onclick="moveGalleryImage(${index}, 1)"
                    ${index === window.productGalleryState.length - 1 ? 'disabled' : ''} title="Move Later" aria-label="Move Later">
              <i class="ri-arrow-right-s-line"></i>
            </button>
          </div>
        </div>
      `;
    });

    galleryPreviewContainer.innerHTML = html;
  };

  window.addGalleryImage = function (url) {
    const trimmed = (url || '').trim();
    if (!trimmed) {
      window.showToast('Please enter a valid image URL', 'warning');
      return;
    }
    window.productGalleryState.push(trimmed);
    if (newImageUrlInput) newImageUrlInput.value = '';
    window.renderProductGallery();
  };

  window.removeGalleryImage = function (index) {
    if (index >= 0 && index < window.productGalleryState.length) {
      window.productGalleryState.splice(index, 1);
      window.renderProductGallery();
    }
  };

  window.moveGalleryImage = function (index, direction) {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= window.productGalleryState.length) return;
    const item = window.productGalleryState.splice(index, 1)[0];
    window.productGalleryState.splice(targetIndex, 0, item);
    window.renderProductGallery();
  };

  window.setGalleryPrimary = function (index) {
    if (index > 0 && index < window.productGalleryState.length) {
      const item = window.productGalleryState.splice(index, 1)[0];
      window.productGalleryState.unshift(item);
      window.renderProductGallery();
    }
  };

  if (addImageUrlBtn) {
    addImageUrlBtn.addEventListener('click', function () {
      if (newImageUrlInput) addGalleryImage(newImageUrlInput.value);
    });
  }

  if (newImageUrlInput) {
    newImageUrlInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        addGalleryImage(this.value);
      }
    });
  }

  // -------------------------------------------------------------------------
  // 5. Product Add / Edit / Variant Creation Modals
  // -------------------------------------------------------------------------
  const productModalEl = document.getElementById('productModal');
  const productForm = document.getElementById('productForm');
  const productModalTitle = document.getElementById('productModalTitle');
  const productIdInput = document.getElementById('modalProductId');

  window.openAddProductModal = function () {
    if (!productForm) return;
    productForm.reset();
    if (productIdInput) productIdInput.value = '';
    if (productModalTitle) {
      productModalTitle.innerHTML = '<i class="ri-shopping-bag-3-line text-danger me-2"></i>Add New Product (SKU)';
    }
    const delBtn = document.getElementById('modalDeleteProductBtn');
    if (delBtn) delBtn.classList.add('d-none');


    window.productGalleryState = [];
    window.renderProductGallery();

    const modal = bootstrap.Modal.getOrCreateInstance(productModalEl);
    modal.show();
  };

  window.openEditProductModal = function (product) {
    if (!productForm) return;
    productForm.reset();
    if (productIdInput) productIdInput.value = product.id;
    const delBtn = document.getElementById('modalDeleteProductBtn');
    if (delBtn) delBtn.classList.remove('d-none');
    if (productModalTitle) {
      productModalTitle.innerHTML = `<i class="ri-edit-line text-primary me-2"></i>Edit Product: ${product.name}`;
    }

    document.getElementById('modalName').value = product.name || '';
    document.getElementById('modalSku').value = product.sku || '';
    document.getElementById('modalBarcode').value = product.barcode !== '-' ? (product.barcode || '') : '';
    document.getElementById('modalCategoryId').value = product.category_id || '';
    document.getElementById('modalBrandId').value = product.brand_id || '';
    document.getElementById('modalUnit').value = product.unit || 'piece';
    document.getElementById('modalPackSize').value = product.pack_size_label !== '-' ? (product.pack_size_label || '') : '';
    document.getElementById('modalPrice').value = product.price || '';
    document.getElementById('modalComparePrice').value = product.compare_at_price || '';
    document.getElementById('modalCostPrice').value = product.cost_price || '';
    document.getElementById('modalTaxClass').value = product.tax_class || 'standard';
    document.getElementById('modalStock').value = product.quantity_on_hand || '0';
    document.getElementById('modalReorderLevel').value = product.reorder_level || '0';
    document.getElementById('modalDescription').value = product.description || '';

    const ageCheck = document.getElementById('modalAgeRestricted');
    if (ageCheck) ageCheck.checked = Boolean(product.is_age_restricted);

    // Populate gallery images
    if (Array.isArray(product.gallery_images) && product.gallery_images.length > 0) {
      window.productGalleryState = product.gallery_images.slice();
    } else if (product.image_url) {
      window.productGalleryState = [product.image_url];
    } else {
      window.productGalleryState = [];
    }
    window.renderProductGallery();

    const modal = bootstrap.Modal.getOrCreateInstance(productModalEl);
    modal.show();
  };

  window.openAddVariantModal = function (product) {
    if (!productForm) return;
    productForm.reset();
    if (productIdInput) productIdInput.value = '';
    if (productModalTitle) {
      productModalTitle.innerHTML = `<i class="ri-node-tree text-warning me-2"></i>Add Size Variant for: ${product.name}`;
    }
    const delBtn = document.getElementById('modalDeleteProductBtn');
    if (delBtn) delBtn.classList.add('d-none');


    // Pre-fill parent product attributes
    document.getElementById('modalCategoryId').value = product.category_id || '';
    document.getElementById('modalBrandId').value = product.brand_id || '';
    document.getElementById('modalUnit').value = product.unit || 'piece';
    document.getElementById('modalTaxClass').value = product.tax_class || 'standard';
    document.getElementById('modalCostPrice').value = product.cost_price || '';

    // Suggest variant name and base SKU prefix
    const baseName = product.name.replace(/\s\d+(\.\d+)?\s*(kg|g|ml|l|piece|pack).*$/i, '').trim();
    document.getElementById('modalName').value = baseName + ' ';
    document.getElementById('modalSku').value = (product.sku || '').replace(/-[A-Z0-9]+$/, '') + '-';

    // Clone parent gallery for rapid variant creation
    if (Array.isArray(product.gallery_images) && product.gallery_images.length > 0) {
      window.productGalleryState = product.gallery_images.slice();
    } else if (product.image_url) {
      window.productGalleryState = [product.image_url];
    } else {
      window.productGalleryState = [];
    }
    window.renderProductGallery();

    const modal = bootstrap.Modal.getOrCreateInstance(productModalEl);
    modal.show();
    setTimeout(() => {
      document.getElementById('modalPackSize')?.focus();
    }, 400);
  };

  if (productForm) {
    productForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      syncGalleryInputs();

      const prodId = productIdInput?.value;
      const isEdit = Boolean(prodId);
      const url = isEdit ? `${BASE_URL}/products/${prodId}` : `${BASE_URL}/products`;
      const method = isEdit ? 'PATCH' : 'POST';

      const saveBtn = document.getElementById('saveProductBtn');
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';
      }

      const formData = new FormData(productForm);
      try {
        const response = await fetch(url, {
          method: method,
          body: formData,
        });

        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.detail || 'Could not save product');
        }

        const data = await response.json();
        window.showToast(data.detail || 'Product saved successfully!', 'success');
        const modal = bootstrap.Modal.getInstance(productModalEl);
        if (modal) modal.hide();
        setTimeout(() => window.location.reload(), 1000);
      } catch (err) {
        window.showToast(err.message, 'error');
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.innerHTML = '<i class="ri-save-line me-1"></i> Save Product SKU';
        }
      }
    });
  }

  // Toggle Product Active Status with Modal Confirmation
  window.toggleProductStatus = function (productId) {
    window.confirmAction({
      title: 'Toggle Product Availability',
      message: 'Are you sure you want to change the active visibility of this product on the catalogue?',
      confirmBtnText: 'Update Visibility',
      confirmBtnClass: 'btn-bansi-red',
      onConfirm: async () => {
        try {
          const response = await fetch(`${BASE_URL}/products/${productId}/toggle-status`, {
            method: 'POST',
          });
          if (!response.ok) throw new Error('Status update failed');
          const data = await response.json();
          window.showToast(data.detail, 'success');
          setTimeout(() => window.location.reload(), 800);
        } catch (err) {
          window.showToast(err.message, 'error');
        }
      },
    });
  };

  // Delete Product SKU Action with Modal Confirmation
  window.deleteProductAction = function (productId, productName) {
    window.confirmAction({
      title: 'Delete Product SKU',
      message: `Are you sure you want to delete "${productName || 'this product'}"? If it has historical sales or stock movements, it will be safely deactivated and archived; otherwise, it will be permanently removed.`,
      confirmBtnText: 'Delete SKU',
      confirmBtnClass: 'btn-danger',
      onConfirm: async () => {
        try {
          const response = await fetch(`${BASE_URL}/products/${productId}`, {
            method: 'DELETE',
          });
          if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Failed to delete product');
          }
          const data = await response.json();
          window.showToast(data.detail, 'success');
          setTimeout(() => window.location.reload(), 900);
        } catch (err) {
          window.showToast(err.message, 'error');
        }
      },
    });
  };

  window.deleteProductFromModal = function () {
    const prodId = productIdInput?.value;
    const prodName = document.getElementById('modalName')?.value || 'this product';
    if (!prodId) return;
    const modal = bootstrap.Modal.getInstance(productModalEl);
    if (modal) modal.hide();
    window.deleteProductAction(prodId, prodName);
  };

  // -------------------------------------------------------------------------
  // 6. Bulk Spreadsheet Operations
  // -------------------------------------------------------------------------
  window.openBulkModal = function () {
    const modalEl = document.getElementById('bulkModal');
    if (modalEl) {
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
    }
  };

  const bulkUploadForm = document.getElementById('bulkUploadForm');
  if (bulkUploadForm) {
    bulkUploadForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const fileInput = document.getElementById('bulkCsvFile');
      if (!fileInput || !fileInput.files.length) {
        window.showToast('Please select a CSV spreadsheet to upload', 'warning');
        return;
      }

      const uploadBtn = document.getElementById('bulkUploadBtn');
      if (uploadBtn) {
        uploadBtn.disabled = true;
        uploadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Processing...';
      }

      const formData = new FormData();
      formData.append('file', fileInput.files[0]);

      try {
        const response = await fetch(`${BASE_URL}/products/bulk-upload`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          const err = await response.json();
          throw new Error(err.detail || 'Bulk upload failed');
        }

        const report = await response.json();
        const msg = `Bulk Import Complete: ${report.created_count} created, ${report.updated_count} updated. Errors: ${report.errors?.length || 0}`;
        window.showToast(msg, report.errors?.length ? 'warning' : 'success');

        const modalEl = document.getElementById('bulkModal');
        const modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();
        setTimeout(() => window.location.reload(), 1500);
      } catch (err) {
        window.showToast(err.message, 'error');
      } finally {
        if (uploadBtn) {
          uploadBtn.disabled = false;
          uploadBtn.innerHTML = '<i class="ri-upload-cloud-2-line me-1"></i> Upload Spreadsheet';
        }
      }
    });
  }

  // -------------------------------------------------------------------------
  // 7. System Actors Regulation with Modal Confirmations
  // -------------------------------------------------------------------------
  // Rider Vetting
  window.vetRiderAction = function (riderId, action, riderName) {
    const verb = action === 'approve' ? 'approve and certify' : (action === 'suspend' ? 'suspend' : 'reject');
    window.confirmAction({
      title: `${action.toUpperCase()} Delivery Rider`,
      message: `Are you sure you want to ${verb} rider "${riderName || 'ID #' + riderId}" for dispatch deliveries?`,
      confirmBtnText: `${action.charAt(0).toUpperCase() + action.slice(1)} Rider`,
      confirmBtnClass: action === 'approve' ? 'btn-success' : (action === 'suspend' ? 'btn-warning' : 'btn-danger'),
      onConfirm: async () => {
        try {
          const formData = new FormData();
          formData.append('action', action);
          const res = await fetch(`${BASE_URL}/actors/riders/${riderId}/vet`, {
            method: 'POST',
            body: formData,
          });
          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Vetting action failed');
          }
          const data = await res.json();
          window.showToast(data.detail, 'success');
          setTimeout(() => window.location.reload(), 800);
        } catch (err) {
          window.showToast(err.message, 'error');
        }
      },
    });
  };

  // Staff Shift Duty Toggle
  window.toggleStaffDutyAction = function (staffId, staffName, currentStatus) {
    const nextState = currentStatus ? 'Off Shift' : 'On Duty';
    window.confirmAction({
      title: 'Toggle Store Staff Shift',
      message: `Change shift duty status of "${staffName}" to ${nextState}?`,
      confirmBtnText: 'Toggle Shift',
      confirmBtnClass: 'btn-primary',
      onConfirm: async () => {
        try {
          const res = await fetch(`${BASE_URL}/actors/staff/${staffId}/toggle-duty`, {
            method: 'POST',
          });
          if (!res.ok) throw new Error('Duty toggle failed');
          const data = await res.json();
          window.showToast(data.detail, 'success');
          setTimeout(() => window.location.reload(), 800);
        } catch (err) {
          window.showToast(err.message, 'error');
        }
      },
    });
  };

  // Superadmin: Update Admin Level with Confirmation & Revert on Cancel
  window.changeAdminLevelPrompt = function (selectEl, adminId, adminName) {
    const previousLevel = selectEl.getAttribute('data-current-level');
    const newLevel = selectEl.value;

    if (previousLevel === newLevel) return;

    window.confirmAction({
      title: 'Change Administrator Authority Level',
      message: `Are you sure you want to change administrative privileges of "${adminName}" from ${previousLevel.toUpperCase()} to ${newLevel.toUpperCase()}?`,
      confirmBtnText: 'Update Authority Level',
      confirmBtnClass: 'btn-bansi-red',
      onConfirm: async () => {
        try {
          const formData = new FormData();
          formData.append('new_level', newLevel);
          const res = await fetch(`${BASE_URL}/actors/admins/${adminId}/level`, {
            method: 'PATCH',
            body: formData,
          });
          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Admin level update failed');
          }
          const data = await res.json();
          selectEl.setAttribute('data-current-level', newLevel);
          window.showToast(data.detail, 'success');
          setTimeout(() => window.location.reload(), 800);
        } catch (err) {
          selectEl.value = previousLevel;
          window.showToast(err.message, 'error');
        }
      },
      onCancel: () => {
        selectEl.value = previousLevel;
      },
    });
  };

  // User Account Status Toggle (Customers, Admins)
  window.toggleUserStatusAction = function (userId, userName, currentActive, role) {
    const actionVerb = currentActive ? 'deactivate' : 'reactivate';
    window.confirmAction({
      title: `${actionVerb.toUpperCase()} ${role.toUpperCase()} Account`,
      message: `Are you sure you want to ${actionVerb} the account for "${userName}" (User #${userId})?`,
      confirmBtnText: `${actionVerb.charAt(0).toUpperCase() + actionVerb.slice(1)} Account`,
      confirmBtnClass: currentActive ? 'btn-danger' : 'btn-success',
      onConfirm: async () => {
        try {
          const res = await fetch(`${BASE_URL}/actors/users/${userId}/toggle-status`, {
            method: 'POST',
          });
          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Account status update failed');
          }
          const data = await res.json();
          window.showToast(data.detail, 'success');
          setTimeout(() => window.location.reload(), 800);
        } catch (err) {
          window.showToast(err.message, 'error');
        }
      },
    });
  };

  // -------------------------------------------------------------------------
  // 8. Administrator Two-Factor Authentication (2FA) Lifecycle
  // -------------------------------------------------------------------------
  const start2faBtn = document.getElementById('start2faBtn');
  const resend2faBtn = document.getElementById('resend2faBtn');
  const twoFactorModalEl = document.getElementById('twoFactorModal');
  const twoFactorForm = document.getElementById('twoFactorForm');
  const twoFactorOtpInput = document.getElementById('twoFactorOtpInput');
  const disable2faBtn = document.getElementById('disable2faBtn');

  async function requestTwoFactorOtp() {
    try {
      const res = await fetch(`${BASE_URL}/security/2fa/request`, {
        method: 'POST',
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Could not initiate 2FA verification');
      }
      const data = await res.json();
      window.showToast(data.detail, 'success');

      if (twoFactorModalEl) {
        const modal = bootstrap.Modal.getOrCreateInstance(twoFactorModalEl);
        modal.show();
        setTimeout(() => twoFactorOtpInput?.focus(), 400);
      }
    } catch (err) {
      window.showToast(err.message, 'error');
    }
  }

  if (start2faBtn) {
    start2faBtn.addEventListener('click', requestTwoFactorOtp);
  }

  if (resend2faBtn) {
    resend2faBtn.addEventListener('click', requestTwoFactorOtp);
  }

  if (twoFactorForm) {
    twoFactorForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const code = (twoFactorOtpInput?.value || '').trim();
      if (!code) {
        window.showToast('Please enter the 6-digit verification code', 'warning');
        return;
      }

      const submitBtn = document.getElementById('submit2faBtn');
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Verifying...';
      }

      const formData = new FormData();
      formData.append('code', code);

      try {
        const res = await fetch(`${BASE_URL}/security/2fa/confirm`, {
          method: 'POST',
          body: formData,
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Invalid or expired verification code');
        }

        const data = await res.json();
        window.showToast(data.detail, 'success');

        const modal = bootstrap.Modal.getInstance(twoFactorModalEl);
        if (modal) modal.hide();
        setTimeout(() => window.location.reload(), 1200);
      } catch (err) {
        window.showToast(err.message, 'error');
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = '<i class="ri-check-line me-1"></i> Verify & Enable 2FA';
        }
      }
    });
  }

  if (disable2faBtn) {
    disable2faBtn.addEventListener('click', function () {
      window.confirmAction({
        title: 'Disable Two-Factor Authentication',
        message: 'Are you sure you want to disable 2FA? Your account will only be protected by your password.',
        confirmBtnText: 'Disable 2FA',
        confirmBtnClass: 'btn-danger',
        onConfirm: async () => {
          try {
            const res = await fetch(`${BASE_URL}/security/2fa/disable`, {
              method: 'POST',
            });
            if (!res.ok) {
              const err = await res.json();
              throw new Error(err.detail || 'Could not disable 2FA');
            }
            const data = await res.json();
            window.showToast(data.detail, 'success');
            setTimeout(() => window.location.reload(), 1000);
          } catch (err) {
            window.showToast(err.message, 'error');
          }
        },
      });
    });
  }

  // -------------------------------------------------------------------------
  // 9. Security & Governance Settings Form
  // -------------------------------------------------------------------------
  const securityForm = document.getElementById('securitySettingsForm');
  if (securityForm) {
    securityForm.addEventListener('submit', function (e) {
      e.preventDefault();
      window.confirmAction({
        title: 'Save Security & Platform Configurations',
        message: 'Apply these session timeouts, M-Pesa gateway settings, and platform security rules system-wide?',
        confirmBtnText: 'Save & Apply Policies',
        confirmBtnClass: 'btn-bansi-red',
        onConfirm: async () => {
          const saveBtn = document.getElementById('saveSecurityBtn');
          if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving Policies...';
          }

          const formData = new FormData(securityForm);
          try {
            const res = await fetch(`${BASE_URL}/security/settings`, {
              method: 'POST',
              body: formData,
            });
            if (!res.ok) {
              const err = await res.json();
              throw new Error(err.detail || 'Security policy update failed');
            }
            const data = await res.json();
            window.showToast(data.detail, 'success');
          } catch (err) {
            window.showToast(err.message, 'error');
          } finally {
            if (saveBtn) {
              saveBtn.disabled = false;
              saveBtn.innerHTML = '<i class="ri-save-line me-1"></i> Save Security Configurations';
            }
          }
        },
      });
    });
  }

  // -------------------------------------------------------------------------
  // 10. Administrator Personal Account Settings Forms
  // -------------------------------------------------------------------------
  const adminProfileForm = document.getElementById('adminProfileForm');
  if (adminProfileForm) {
    adminProfileForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const saveBtn = document.getElementById('saveProfileBtn');
      if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Saving...';
      }

      const formData = new FormData(adminProfileForm);
      try {
        const res = await fetch(`${BASE_URL}/account/profile`, {
          method: 'POST',
          body: formData,
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Could not update profile details');
        }

        const data = await res.json();
        window.showToast(data.detail || 'Profile details updated successfully!', 'success');
        setTimeout(() => window.location.reload(), 1000);
      } catch (err) {
        window.showToast(err.message, 'error');
      } finally {
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.innerHTML = '<i class="ri-save-line me-1"></i> Save Profile Details';
        }
      }
    });
  }

  const adminPasswordForm = document.getElementById('adminPasswordForm');
  if (adminPasswordForm) {
    adminPasswordForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const newPass = document.getElementById('newPassword')?.value;
      const confirmPass = document.getElementById('newPasswordConfirm')?.value;

      if (newPass !== confirmPass) {
        window.showToast('New passwords do not match', 'warning');
        return;
      }

      if (newPass.length < 8) {
        window.showToast('Password must be at least 8 characters long', 'warning');
        return;
      }

      const updateBtn = document.getElementById('updatePasswordBtn');
      if (updateBtn) {
        updateBtn.disabled = true;
        updateBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Updating...';
      }

      const formData = new FormData(adminPasswordForm);
      try {
        const res = await fetch(`${BASE_URL}/account/password`, {
          method: 'POST',
          body: formData,
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || 'Password update failed');
        }

        const data = await res.json();
        window.showToast(data.detail || 'Password updated successfully!', 'success');
        adminPasswordForm.reset();
      } catch (err) {
        window.showToast(err.message, 'error');
      } finally {
        if (updateBtn) {
          updateBtn.disabled = false;
          updateBtn.innerHTML = '<i class="ri-key-2-line me-1"></i> Update Password';
        }
      }
    });
  }

  // -------------------------------------------------------------------------
  // Dispatch & Manual Assignment Operations
  // -------------------------------------------------------------------------
  window.manualAssignDelivery = async function (deliveryId) {
    const select = document.getElementById(`assignRider_${deliveryId}`);
    const riderId = select ? select.value : '';
    if (!riderId) {
      window.showToast('Please select an online approved rider first.', 'warning');
      return;
    }
    const fd = new FormData();
    fd.append('rider_id', riderId);
    const res = await fetch(`${BASE_URL}/deliveries/${deliveryId}/assign`, { method: 'POST', body: fd });
    const data = await res.json();
    if (res.ok) {
      window.location.hash = 'dispatch';
      window.location.reload();
    } else {
      window.showToast(data.detail || 'Manual assignment failed', 'error');
    }
  };

  window.autoDispatchDelivery = async function (deliveryId) {
    const res = await fetch(`${BASE_URL}/deliveries/${deliveryId}/auto-dispatch`, { method: 'POST' });
    const data = await res.json();
    window.showToast(data.detail || 'Dispatch attempted', data.assigned ? 'success' : 'warning');
    window.location.hash = 'dispatch';
    window.location.reload();
  };

  window.triggerSlaSweep = async function () {
    const res = await fetch(`${BASE_URL}/deliveries/sweep`, { method: 'POST' });
    const data = await res.json();
    window.showToast(data.detail || 'SLA Sweep completed', 'success');
    window.location.hash = 'dispatch';
    window.location.reload();
  };

  window.verifyStorePickup = async function (deliveryId) {
    const input = document.getElementById(`verifyPickupCode_${deliveryId}`);
    const code = input ? input.value.trim() : '';
    if (!code || code.length < 4) {
      window.showToast('Please enter the 4-digit pickup code presented by the rider.', 'warning');
      return;
    }
    const form = new FormData();
    form.append('pickup_code', code);
    const res = await fetch(`${BASE_URL}/deliveries/${deliveryId}/verify-pickup`, { method: 'POST', body: form });
    const data = await res.json();
    if (res.ok) {
      window.showToast(data.detail || 'Pickup verified!', 'success');
      window.location.hash = 'dispatch';
      window.location.reload();
    } else {
      window.showToast(data.detail || 'Incorrect pickup code.', 'error');
    }
  };

  // -------------------------------------------------------------------------
  // 11. Rider Vetting Submission Modal (Documents & Approval)
  // -------------------------------------------------------------------------
  window.openRiderSubmissionModal = async function (riderId) {
    const modalEl = document.getElementById('riderVettingModal');
    const bodyEl = document.getElementById('rvModalBody');
    const subEl = document.getElementById('rvModalSubtitle');
    const actionsEl = document.getElementById('rvModalActions');
    if (!modalEl || !bodyEl) return;

    bodyEl.innerHTML = '<div class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm text-primary me-2"></div>Loading rider submission...</div>';
    if (actionsEl) actionsEl.innerHTML = '';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();

    try {
      const res = await fetch(`${BASE_URL}/actors/riders/${riderId}`);
      if (!res.ok) throw new Error('Could not load rider details');
      const r = await res.json();
      if (subEl) subEl.textContent = `${r.name} • ${r.phone} • ${r.vehicle_type.toUpperCase()} (${r.vehicle_plate || 'No Plate'})`;

      const docCard = (title, url) => `
        <div class="col-md-6">
          <div class="border rounded-3 p-2 bansi-subtle-box h-100">
            <div class="small fw-semibold mb-2">${title}</div>
            ${url ? `<a href="${url}" target="_blank"><img src="${url}" alt="${title}" class="img-fluid rounded border" style="max-height:170px;width:100%;object-fit:cover;" onerror="this.outerHTML='<div class=\\'text-muted small py-3 text-center\\'>Document preview unavailable (${url})</div>'"></a>` : '<div class="text-muted small py-3 text-center">Not uploaded</div>'}
          </div>
        </div>`;

      bodyEl.innerHTML = `
        <div class="row g-3 mb-3 small">
          <div class="col-md-4"><span class="text-muted d-block">National ID #</span><strong>${r.national_id_number || '-'}</strong></div>
          <div class="col-md-4"><span class="text-muted d-block">Licence # / Expiry</span><strong>${r.licence_number || '-'} (${r.licence_expiry || 'N/A'})</strong></div>
          <div class="col-md-4"><span class="text-muted d-block">Status / Rating</span><strong class="text-uppercase">${r.approval_status}</strong> &middot; ★ ${r.rating_average} (${r.rating_count})</div>
        </div>
        <div class="row g-3">
          ${docCard('National ID Front', r.id_card_front_url)}
          ${docCard('National ID Back', r.id_card_back_url)}
          ${docCard('Driving Licence', r.driving_licence_url)}
          ${docCard('Vehicle Proof / Logbook', r.vehicle_proof_url)}
        </div>`;

      if (actionsEl && (window.ADMIN_LEVEL === 'super' || window.ADMIN_LEVEL === 'operations')) {
        actionsEl.innerHTML = `
          ${r.approval_status !== 'approved' ? `<button type="button" class="btn btn-sm btn-success" onclick="vetRiderAction(${r.id}, 'approve', '${r.name.replace(/'/g, "\\'")}')"><i class="ri-check-line me-1"></i>Approve</button>` : ''}
          ${r.approval_status !== 'suspended' ? `<button type="button" class="btn btn-sm btn-warning" onclick="vetRiderAction(${r.id}, 'suspend', '${r.name.replace(/'/g, "\\'")}')">Suspend</button>` : ''}
          ${r.approval_status !== 'rejected' ? `<button type="button" class="btn btn-sm btn-outline-danger" onclick="vetRiderAction(${r.id}, 'reject', '${r.name.replace(/'/g, "\\'")}')">Reject</button>` : ''}`;
      }
    } catch (err) {
      bodyEl.innerHTML = `<div class="alert alert-danger small mb-0">${err.message}</div>`;
    }
  };

  // -------------------------------------------------------------------------
  // 12. Orders Filtering, Inspection & Picking
  // -------------------------------------------------------------------------
  const orderSearchInput = document.getElementById('orderSearchInput');
  const orderStatusFilter = document.getElementById('orderStatusFilter');
  function filterOrdersTable() {
    const q = (orderSearchInput?.value || '').toLowerCase().trim();
    const st = (orderStatusFilter?.value || '').toLowerCase();
    document.querySelectorAll('.order-table-row').forEach(row => {
      const hay = (row.getAttribute('data-search') || '').toLowerCase();
      const rowSt = (row.getAttribute('data-status') || '').toLowerCase();
      row.style.display = ((!q || hay.includes(q)) && (!st || rowSt === st)) ? '' : 'none';
    });
  }
  if (orderSearchInput) orderSearchInput.addEventListener('input', filterOrdersTable);
  if (orderStatusFilter) orderStatusFilter.addEventListener('change', filterOrdersTable);

  window.openOrderDetailModal = async function (orderId) {
    const modalEl = document.getElementById('orderDetailModal');
    const bodyEl = document.getElementById('odModalBody');
    const titleEl = document.getElementById('odModalTitle');
    const subEl = document.getElementById('odModalSubtitle');
    const actionsEl = document.getElementById('odModalActions');
    if (!modalEl || !bodyEl) return;

    bodyEl.innerHTML = '<div class="text-center py-4 text-muted"><div class="spinner-border spinner-border-sm text-primary me-2"></div>Loading order...</div>';
    if (actionsEl) actionsEl.innerHTML = '';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();

    try {
      const res = await fetch(`${BASE_URL}/orders/${orderId}`);
      if (!res.ok) throw new Error('Failed to load order detail');
      const o = await res.json();
      if (titleEl) titleEl.textContent = `Order #${o.order_number}`;
      if (subEl) subEl.textContent = `${o.customer_name} (${o.recipient_phone}) • ${o.fulfilment_type.toUpperCase()} • ${o.status.toUpperCase()}`;

      const canPick = (window.ADMIN_LEVEL === 'super' || window.ADMIN_LEVEL === 'operations') && o.status === 'preparing';
      const itemsHtml = (o.items || []).map(it => `
        <tr>
          <td><div class="fw-semibold small">${it.product_name}</div><code style="font-size:0.7rem;">${it.sku}</code></td>
          <td>${it.quantity} ${it.unit}</td>
          <td>KES ${it.unit_price}</td>
          <td><span class="badge bansi-subtle-box border text-uppercase">${it.pick_status}</span></td>
          <td class="text-end">
            ${canPick && it.pick_status === 'pending' ? `
              <div class="btn-group btn-group-xs">
                <button type="button" class="btn btn-xs btn-success" onclick="pickOrderItem(${o.id}, ${it.id}, 'picked', '${it.quantity}')">Picked</button>
                <button type="button" class="btn btn-xs btn-outline-danger" onclick="pickOrderItem(${o.id}, ${it.id}, 'out_of_stock', '0')">OOS</button>
              </div>
            ` : `<span class="small fw-semibold">KES ${it.line_total}</span>`}
          </td>
        </tr>`).join('');

      bodyEl.innerHTML = `
        <div class="row g-3 mb-3 small">
          <div class="col-md-4"><span class="text-muted d-block">Delivery Address</span><strong>${o.address_text}</strong></div>
          <div class="col-md-4"><span class="text-muted d-block">Payment</span><strong>${o.payment_method.toUpperCase()} (${o.payment_status.toUpperCase()})</strong></div>
          <div class="col-md-4"><span class="text-muted d-block">Total (incl. VAT ${o.tax_total})</span><strong class="text-primary">KES ${o.total}</strong></div>
        </div>
        ${o.customer_note ? `<div class="alert alert-info py-2 px-3 small mb-3"><strong>Customer Note:</strong> ${o.customer_note}</div>` : ''}
        <div class="table-responsive mb-3">
          <table class="table bansi-table table-sm mb-0 align-middle">
            <thead><tr><th>Item</th><th>Qty</th><th>Unit Price</th><th>Pick Status</th><th class="text-end">Action / Total</th></tr></thead>
            <tbody>${itemsHtml}</tbody>
          </table>
        </div>
        <div class="small text-muted">
          <strong>Timeline:</strong> ${(o.history || []).map(h => `${h.to_status} (${h.created_at})`).join(' &rarr; ')}
        </div>`;

      if (actionsEl) {
        let btns = '';
        if ((window.ADMIN_LEVEL === 'super' || window.ADMIN_LEVEL === 'operations')) {
          if (o.status === 'confirmed') {
            btns += `<button type="button" class="btn btn-sm btn-warning" onclick="startOrderPicking(${o.id}, '${o.order_number}')">Start Picking</button>`;
          } else if (o.status === 'preparing') {
            btns += `<button type="button" class="btn btn-sm btn-success" onclick="finishOrderPicking(${o.id}, '${o.order_number}')">Finish Picking &amp; Ready</button>`;
          } else if (o.status === 'ready' && o.fulfilment_type === 'pickup') {
            btns += `<button type="button" class="btn btn-sm btn-success" onclick="completePickupOrder(${o.id}, '${o.order_number}')">Complete Store Pickup</button>`;
          }
        }
        if ((window.ADMIN_LEVEL === 'super' || window.ADMIN_LEVEL === 'operations' || window.ADMIN_LEVEL === 'support') && !['completed', 'cancelled'].includes(o.status)) {
          btns += `<button type="button" class="btn btn-sm btn-outline-danger" onclick="cancelOrderByAdmin(${o.id}, '${o.order_number}')">Cancel Order</button>`;
        }
        actionsEl.innerHTML = btns;
      }
    } catch (err) {
      bodyEl.innerHTML = `<div class="alert alert-danger small mb-0">${err.message}</div>`;
    }
  };

  window.startOrderPicking = async function (orderId, orderNumber) {
    const res = await fetch(`${BASE_URL}/orders/${orderId}/start-picking`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      window.showToast(data.detail || `Picking started for #${orderNumber}`, 'success');
      window.openOrderDetailModal(orderId);
    } else {
      window.showToast(data.detail || 'Could not start picking', 'error');
    }
  };

  window.pickOrderItem = async function (orderId, itemId, pickStatus, qty) {
    const fd = new FormData();
    fd.append('pick_status', pickStatus);
    fd.append('quantity_picked', qty);
    const res = await fetch(`${BASE_URL}/orders/${orderId}/items/${itemId}/pick`, { method: 'POST', body: fd });
    const data = await res.json();
    if (res.ok) {
      window.showToast(data.detail || 'Item picked', 'success');
      window.openOrderDetailModal(orderId);
    } else {
      window.showToast(data.detail || 'Pick failed', 'error');
    }
  };

  window.finishOrderPicking = async function (orderId, orderNumber) {
    const res = await fetch(`${BASE_URL}/orders/${orderId}/finish-picking`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      window.showToast(data.detail || `Order #${orderNumber} packed`, 'success');
      setTimeout(() => { window.location.hash = 'orders'; window.location.reload(); }, 800);
    } else {
      window.showToast(data.detail || 'Could not finish picking', 'error');
    }
  };

  window.completePickupOrder = async function (orderId, orderNumber) {
    const res = await fetch(`${BASE_URL}/orders/${orderId}/complete-pickup`, { method: 'POST' });
    const data = await res.json();
    if (res.ok) {
      window.showToast(data.detail || `Order #${orderNumber} completed`, 'success');
      setTimeout(() => { window.location.hash = 'orders'; window.location.reload(); }, 800);
    } else {
      window.showToast(data.detail || 'Could not complete pickup', 'error');
    }
  };

  window.cancelOrderByAdmin = function (orderId, orderNumber) {
    window.confirmAction({
      title: `Cancel Order #${orderNumber}`,
      message: 'Cancel this order, release reserved stock, and trigger a refund request if already paid?',
      confirmBtnText: 'Cancel Order',
      confirmBtnClass: 'btn-danger',
      onConfirm: async () => {
        const fd = new FormData();
        fd.append('reason', 'Cancelled by BansiGo Admin Console');
        const res = await fetch(`${BASE_URL}/orders/${orderId}/cancel`, { method: 'POST', body: fd });
        const data = await res.json();
        if (res.ok) {
          window.showToast(data.detail || 'Order cancelled', 'success');
          setTimeout(() => { window.location.hash = 'orders'; window.location.reload(); }, 800);
        } else {
          window.showToast(data.detail || 'Cancellation failed', 'error');
        }
      },
    });
  };

  // -------------------------------------------------------------------------
  // 13. Inventory Stock Operations, Suppliers & Delivery Zones
  // -------------------------------------------------------------------------
  window.openStockActionModal = function (productId, productName, actionType, currentOnHand) {
    const modalEl = document.getElementById('stockActionModal');
    if (!modalEl) return;
    document.getElementById('stockActionProductId').value = productId;
    document.getElementById('stockActionType').value = actionType;
    document.getElementById('stockActionProductInfo').textContent = `${productName} (Current on hand: ${currentOnHand})`;

    const titleMap = { receive: 'Receive Supplier Stock', stock_take: 'Physical Stock Take', write_off: 'Record Wastage / Write-Off' };
    const labelMap = { receive: 'Quantity Received *', stock_take: 'Counted Quantity on Shelf *', write_off: 'Quantity Written Off *' };
    document.getElementById('stockActionModalTitle').textContent = titleMap[actionType] || 'Stock Adjustment';
    document.getElementById('stockQtyLabel').textContent = labelMap[actionType] || 'Quantity *';
    document.getElementById('stockSupplierGroup').classList.toggle('d-none', actionType !== 'receive');
    document.getElementById('stockUnitCostGroup').classList.toggle('d-none', actionType !== 'receive');
    document.getElementById('stockActionQty').value = actionType === 'stock_take' ? currentOnHand : '';
    document.getElementById('stockActionNote').required = actionType === 'write_off';
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  };

  const stockActionForm = document.getElementById('stockActionForm');
  if (stockActionForm) {
    stockActionForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const pid = document.getElementById('stockActionProductId').value;
      const type = document.getElementById('stockActionType').value;
      const qty = document.getElementById('stockActionQty').value;
      const note = document.getElementById('stockActionNote').value;
      const fd = new FormData();

      let endpoint = `${BASE_URL}/inventory/${pid}/receive`;
      if (type === 'receive') {
        fd.append('quantity', qty);
        const supId = document.getElementById('stockActionSupplier')?.value;
        const unitCost = document.getElementById('stockActionUnitCost')?.value;
        if (supId) fd.append('supplier_id', supId);
        if (unitCost) fd.append('unit_cost', unitCost);
        if (note) fd.append('note', note);
      } else if (type === 'stock_take') {
        endpoint = `${BASE_URL}/inventory/${pid}/stock-take`;
        fd.append('counted', qty);
        if (note) fd.append('note', note);
      } else {
        endpoint = `${BASE_URL}/inventory/${pid}/write-off`;
        fd.append('quantity', qty);
        fd.append('note', note || 'Wastage recorded via console');
      }

      const res = await fetch(endpoint, { method: 'POST', body: fd });
      const data = await res.json();
      if (res.ok) {
        window.showToast(data.detail || 'Inventory updated', 'success');
        setTimeout(() => { window.location.hash = 'inventory'; window.location.reload(); }, 800);
      } else {
        window.showToast(data.detail || 'Inventory update failed', 'error');
      }
    });
  }

  function bindSimpleModalForm(formId, modalId, endpoint, hashTab) {
    const form = document.getElementById(formId);
    if (!form) return;
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      const res = await fetch(endpoint, { method: 'POST', body: new FormData(form) });
      const data = await res.json();
      if (res.ok) {
        window.showToast(data.detail || 'Saved successfully', 'success');
        bootstrap.Modal.getInstance(document.getElementById(modalId))?.hide();
        setTimeout(() => { window.location.hash = hashTab; window.location.reload(); }, 800);
      } else {
        window.showToast(data.detail || 'Operation failed', 'error');
      }
    });
  }

  window.openCreateSupplierModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('supplierModal')).show();
  window.openCreateAdminModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('createAdminModal')).show();
  window.openCreateStaffModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('createStaffModal')).show();
  window.openCreateZoneModal = () => bootstrap.Modal.getOrCreateInstance(document.getElementById('createZoneModal')).show();

  bindSimpleModalForm('supplierForm', 'supplierModal', `${BASE_URL}/suppliers`, 'inventory');
  bindSimpleModalForm('createAdminForm', 'createAdminModal', `${BASE_URL}/actors/admins`, 'actors');
  bindSimpleModalForm('createStaffForm', 'createStaffModal', `${BASE_URL}/actors/staff`, 'actors');
  bindSimpleModalForm('createZoneForm', 'createZoneModal', `${BASE_URL}/dispatch/zones`, 'dispatch');

  window.toggleSupplierStatus = async function (supplierId) {
    const res = await fetch(`${BASE_URL}/suppliers/${supplierId}/toggle-status`, { method: 'POST' });
    const data = await res.json();
    window.showToast(data.detail || 'Supplier updated', res.ok ? 'success' : 'error');
    if (res.ok) setTimeout(() => { window.location.hash = 'inventory'; window.location.reload(); }, 700);
  };

  window.toggleDeliveryZone = async function (zoneId) {
    const res = await fetch(`${BASE_URL}/dispatch/zones/${zoneId}/toggle-status`, { method: 'POST' });
    const data = await res.json();
    window.showToast(data.detail || 'Zone updated', res.ok ? 'success' : 'error');
    if (res.ok) setTimeout(() => { window.location.hash = 'dispatch'; window.location.reload(); }, 700);
  };

  // -------------------------------------------------------------------------
  // 14. Finance Reconciliation, Maker-Checker Refunds & Reviews Moderation
  // -------------------------------------------------------------------------
  window.openManualMpesaModal = function (orderId, orderNumber) {
    document.getElementById('manualMpesaOrderId').value = orderId;
    document.getElementById('manualMpesaSubtitle').textContent = `Reconcile unpaid Order #${orderNumber} against confirmed Safaricom M-Pesa receipt.`;
    document.getElementById('manualMpesaCode').value = '';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('manualMpesaModal')).show();
  };

  const manualMpesaForm = document.getElementById('manualMpesaForm');
  if (manualMpesaForm) {
    manualMpesaForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const orderId = document.getElementById('manualMpesaOrderId').value;
      const fd = new FormData();
      fd.append('transaction_code', document.getElementById('manualMpesaCode').value);
      const res = await fetch(`${BASE_URL}/finance/orders/${orderId}/confirm-manual`, { method: 'POST', body: fd });
      const data = await res.json();
      if (res.ok) {
        window.showToast(data.detail || 'Payment reconciled', 'success');
        setTimeout(() => { window.location.hash = 'orders'; window.location.reload(); }, 800);
      } else {
        window.showToast(data.detail || 'Reconciliation failed', 'error');
      }
    });
  }

  window.openRequestRefundModal = function (paymentId, orderNumber, amount) {
    document.getElementById('refundPaymentId').value = paymentId;
    document.getElementById('refundSubtitle').textContent = `Payment #${paymentId} for Order #${orderNumber} (Max KES ${amount}).`;
    document.getElementById('refundAmount').value = '';
    document.getElementById('refundReason').value = '';
    bootstrap.Modal.getOrCreateInstance(document.getElementById('requestRefundModal')).show();
  };

  const requestRefundForm = document.getElementById('requestRefundForm');
  if (requestRefundForm) {
    requestRefundForm.addEventListener('submit', async function (e) {
      e.preventDefault();
      const fd = new FormData();
      fd.append('payment_id', document.getElementById('refundPaymentId').value);
      const amt = document.getElementById('refundAmount').value;
      if (amt) fd.append('amount', amt);
      fd.append('reason', document.getElementById('refundReason').value);
      const res = await fetch(`${BASE_URL}/finance/refunds`, { method: 'POST', body: fd });
      const data = await res.json();
      if (res.ok) {
        window.showToast(data.detail || 'Refund requested', 'success');
        setTimeout(() => { window.location.hash = 'finance'; window.location.reload(); }, 800);
      } else {
        window.showToast(data.detail || 'Refund request failed', 'error');
      }
    });
  }

  window.approveRefundAction = async function (refundId) {
    const res = await fetch(`${BASE_URL}/finance/refunds/${refundId}/approve`, { method: 'POST' });
    const data = await res.json();
    window.showToast(data.detail || 'Refund approved', res.ok ? 'success' : 'error');
    if (res.ok) setTimeout(() => { window.location.hash = 'finance'; window.location.reload(); }, 700);
  };

  window.rejectRefundAction = function (refundId) {
    window.confirmAction({
      title: `Reject Refund #RF-${refundId}`,
      message: 'Reject this refund request? This cannot be undone.',
      confirmBtnText: 'Reject Refund',
      confirmBtnClass: 'btn-danger',
      onConfirm: async () => {
        const fd = new FormData();
        fd.append('reason', 'Rejected by Finance Controller');
        const res = await fetch(`${BASE_URL}/finance/refunds/${refundId}/reject`, { method: 'POST', body: fd });
        const data = await res.json();
        window.showToast(data.detail || 'Refund rejected', res.ok ? 'success' : 'error');
        if (res.ok) setTimeout(() => { window.location.hash = 'finance'; window.location.reload(); }, 700);
      },
    });
  };

  window.settleRefundAction = async function (refundId) {
    const receipt = `B2C${Date.now().toString().slice(-7)}`;
    const fd = new FormData();
    fd.append('receipt', receipt);
    const res = await fetch(`${BASE_URL}/finance/refunds/${refundId}/settle`, { method: 'POST', body: fd });
    const data = await res.json();
    window.showToast(data.detail || 'Refund settled', res.ok ? 'success' : 'error');
    if (res.ok) setTimeout(() => { window.location.hash = 'finance'; window.location.reload(); }, 700);
  };

  window.toggleReviewPublish = async function (reviewId) {
    const res = await fetch(`${BASE_URL}/reviews/${reviewId}/toggle-publish`, { method: 'POST' });
    const data = await res.json();
    window.showToast(data.detail || 'Review updated', res.ok ? 'success' : 'error');
    if (res.ok) setTimeout(() => { window.location.hash = 'reviews'; window.location.reload(); }, 700);
  };

  const reviewTypeFilter = document.getElementById('reviewTypeFilter');
  const reviewRatingFilter = document.getElementById('reviewRatingFilter');
  function filterReviewsGrid() {
    const typeVal = (reviewTypeFilter?.value || '').toLowerCase();
    const ratingVal = reviewRatingFilter?.value || '';
    document.querySelectorAll('.review-card-col').forEach(card => {
      const t = (card.getAttribute('data-target-type') || '').toLowerCase();
      const r = parseInt(card.getAttribute('data-rating') || '5', 10);
      const matchType = !typeVal || t === typeVal;
      let matchRating = true;
      if (ratingVal === '5') matchRating = r === 5;
      else if (ratingVal === '4') matchRating = r === 4;
      else if (ratingVal === 'critical') matchRating = r <= 3;
      card.style.display = (matchType && matchRating) ? '' : 'none';
    });
  }
  if (reviewTypeFilter) reviewTypeFilter.addEventListener('change', filterReviewsGrid);
  if (reviewRatingFilter) reviewRatingFilter.addEventListener('change', filterReviewsGrid);
});
