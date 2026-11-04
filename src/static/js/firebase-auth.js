// src/static/js/firebase-auth.js

/**
 * BansiGo Firebase & Social Authentication Client
 * Compatible with Firebase Modular SDK v13.2.0
 */

import { initializeApp } from "https://www.gstatic.com/firebasejs/13.2.0/firebase-app.js";
import { getAnalytics } from "https://www.gstatic.com/firebasejs/13.2.0/firebase-analytics.js";
import {
    getAuth,
    signInWithPopup,
    GoogleAuthProvider,
    FacebookAuthProvider,
    signOut as fbSignOut
} from "https://www.gstatic.com/firebasejs/13.2.0/firebase-auth.js";

// Firebase App Configuration
export const firebaseConfig = {
    apiKey: "AIzaSyCK_qeCXmJlFo0vAbaAUwmZcr7GqarAkvg",
    authDomain: "bansigo-customer.firebaseapp.com",
    projectId: "bansigo-customer",
    storageBucket: "bansigo-customer.firebasestorage.app",
    messagingSenderId: "624770085167",
    appId: "1:624770085167:web:f8617d01eb64d9ca3c71da",
    measurementId: "G-GN0J89BE0D"
};

// Initialize Firebase App & Auth
export const app = initializeApp(firebaseConfig);
export const analytics = typeof window !== "undefined" ? getAnalytics(app) : null;
export const auth = getAuth(app);

// Auth Providers
const googleProvider = new GoogleAuthProvider();
googleProvider.addScope("email");
googleProvider.addScope("profile");

const facebookProvider = new FacebookAuthProvider();
facebookProvider.addScope("email");
facebookProvider.addScope("public_profile");

/**
 * Authenticates with Google popup and exchanges token with BansiGo server
 * @param {string|null} optionalPhone
 * @returns {Promise<{access_token: string, user: object, is_new_user: boolean, requires_phone: boolean}>}
 */
export async function signInWithGoogle(optionalPhone = null) {
    try {
        const result = await signInWithPopup(auth, googleProvider);
        const idToken = await result.user.getIdToken();

        return await exchangeSocialToken("google", idToken, optionalPhone);
    } catch (error) {
        console.error("Google sign-in error:", error);
        throw error;
    }
}

/**
 * Authenticates with Facebook popup and exchanges token with BansiGo server
 * @param {string|null} optionalPhone
 * @returns {Promise<{access_token: string, user: object, is_new_user: boolean, requires_phone: boolean}>}
 */
export async function signInWithFacebook(optionalPhone = null) {
    try {
        const result = await signInWithPopup(auth, facebookProvider);
        const idToken = await result.user.getIdToken();

        return await exchangeSocialToken("facebook", idToken, optionalPhone);
    } catch (error) {
        console.error("Facebook sign-in error:", error);
        throw error;
    }
}

/**
 * Sends Firebase ID token to the BansiGo backend
 * @param {string} provider
 * @param {string} token
 * @param {string|null} phone
 */
export async function exchangeSocialToken(provider, token, phone = null) {
    const payload = {
        provider: provider,
        token: token
    };
    if (phone) {
        payload.phone = phone;
    }

    const response = await fetch("/api/auth/social", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        body: JSON.stringify(payload)
    });

    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        const message = errData.detail || "Authentication with server failed";
        throw new Error(message);
    }

    const authData = await response.json();

    // Store BansiGo JWT access token in localStorage
    if (authData.access_token) {
        localStorage.setItem("bansigo_token", authData.access_token);
        localStorage.setItem("bansigo_user", JSON.stringify(authData.user));
    }

    // Trigger global event for UI components to listen to
    window.dispatchEvent(new CustomEvent("bansigo:auth:success", { detail: authData }));

    return authData;
}

/**
 * Completes customer phone number for users without one
 * @param {string} phone
 * @param {string|null} token
 */
export async function completePhone(phone, token = null) {
    const accessToken = token || localStorage.getItem("bansigo_token");
    if (!accessToken) {
        throw new Error("No authentication token available");
    }

    const response = await fetch("/api/auth/complete-phone", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": `Bearer ${accessToken}`
        },
        body: JSON.stringify({ phone: phone })
    });

    if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.detail || "Could not save phone number");
    }

    const updatedUser = await response.json();
    localStorage.setItem("bansigo_user", JSON.stringify(updatedUser));
    window.dispatchEvent(new CustomEvent("bansigo:profile:updated", { detail: updatedUser }));
    return updatedUser;
}

/**
 * Signs out from Firebase and clears local credentials
 */
export async function signOut() {
    try {
        await fbSignOut(auth);
    } catch (e) {
        // ignore
    }
    localStorage.removeItem("bansigo_token");
    localStorage.removeItem("bansigo_user");
    window.dispatchEvent(new CustomEvent("bansigo:auth:logout"));
}

// Expose on window for standard script tags
if (typeof window !== "undefined") {
    window.BansiAuth = {
        signInWithGoogle,
        signInWithFacebook,
        exchangeSocialToken,
        completePhone,
        signOut,
        auth,
        app
    };
}
