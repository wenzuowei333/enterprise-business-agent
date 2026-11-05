package com.demo.management.designsystem

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Test

class LauncherIconGeometryTest {
    @Test
    fun adaptiveIconArtworkIsOpticallyCentered() {
        val foreground = sourceFile("src/main/res/drawable/ic_launcher_foreground.xml")
        val root = DocumentBuilderFactory.newInstance().apply {
            isNamespaceAware = true
        }.newDocumentBuilder().parse(foreground).documentElement
        val namespace = "http://schemas.android.com/apk/res/android"
        val sharedInset = root.getAttributeNS(namespace, "inset").toDpOrNull()
        val left = root.getAttributeNS(namespace, "insetLeft").toDpOrNull() ?: sharedInset ?: 0.0
        val top = root.getAttributeNS(namespace, "insetTop").toDpOrNull() ?: sharedInset ?: 0.0
        val right = root.getAttributeNS(namespace, "insetRight").toDpOrNull() ?: sharedInset ?: 0.0
        val bottom = root.getAttributeNS(namespace, "insetBottom").toDpOrNull() ?: sharedInset ?: 0.0

        assertEquals("The foreground width must stay unchanged", 18.0, left, 0.01)
        assertEquals("The foreground width must stay unchanged", 18.0, right, 0.01)
        assertEquals("The foreground must keep square bounds", left + right, top + bottom, 0.01)
        assertEquals("The source artwork needs a 6dp upward optical correction", 6.0, (bottom - top) / 2, 0.01)
    }

    private fun sourceFile(relativePath: String): File =
        listOf(
            File(relativePath),
            File("app/$relativePath"),
            File("../app/$relativePath"),
        ).firstOrNull(File::isFile)
            ?: error("Unable to locate Android source resource: $relativePath")

    private fun String.toDpOrNull(): Double? =
        takeIf(String::isNotBlank)?.removeSuffix("dp")?.toDoubleOrNull()
}
