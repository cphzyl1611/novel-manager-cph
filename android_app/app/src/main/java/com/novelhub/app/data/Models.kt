package com.novelhub.app.data

data class Book(val id: Long, val title: String, val author: String,
    val chapterCount: Int, val qualityScore: Double?,
    val latestReadAt: String?, val progressRatio: Double)
data class ChapterItem(val index: Int, val title: String, val charCount: Int)
data class ChapterContent(val bookId: Long, val chapterIndex: Int, val title: String,
    val content: String, val encoding: String, val prev: Int?, val next: Int?,
    val totalChapters: Int)
data class BooksResponse(val items: List<Book>, val serverRevision: Long)
data class ChaptersResponse(val bookId: Long, val title: String,
    val chapters: List<ChapterItem>, val note: String?)
