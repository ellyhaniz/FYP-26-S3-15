package com.example.plantdex.common;

import com.example.plantdex.researcher.ResearcherDashboardActivity;
import com.example.plantdex.visitor.VisitorDashboardActivity;

/**
 * Shared role constants and the dashboard each one lands on. Visitor and
 * Researcher have their own dashboards. System Admins may sign in to preview the
 * visitor app (every card shown unlocked; their scans record nothing on the server).
 * User Admins work only in the Django portal. Any other role falls back to the
 * Visitor dashboard here rather than crashing.
 */
public final class Roles {

    public static final String VISITOR = "VISITOR";
    public static final String RESEARCHER = "RESEARCHER";
    public static final String SYSTEM_ADMIN = "SYSTEM ADMIN";

    private Roles() {}

    /** Which dashboard Activity a given role opens after login (or when "Home" is tapped in the bottom nav). */
    public static Class<?> dashboardFor(String role) {
        if (RESEARCHER.equals(role)) {
            return ResearcherDashboardActivity.class;
        }
        return VisitorDashboardActivity.class;
    }

    /** Roles allowed to sign in to the app. */
    public static boolean canUseApp(String role) {
        return VISITOR.equals(role) || RESEARCHER.equals(role) || SYSTEM_ADMIN.equals(role);
    }

    /** A System Admin previewing the visitor app. */
    public static boolean isAdminPreview(String role) {
        return SYSTEM_ADMIN.equals(role);
    }

    /** Roles that get the visitor screens and features (collection progress, discoveries). */
    public static boolean usesVisitorScreens(String role) {
        return VISITOR.equals(role) || SYSTEM_ADMIN.equals(role);
    }

    /** Whether this role's bottom nav includes the camera / identify shortcut. */
    public static boolean hasCameraTab(String role) {
        return true;
    }

    public static String displayId(String role) {
        return RESEARCHER.equals(role) ? "Researcher #ID" : "Visitor #ID";
    }
}
