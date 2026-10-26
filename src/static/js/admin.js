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
});
