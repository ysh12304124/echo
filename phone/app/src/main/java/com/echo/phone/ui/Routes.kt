package com.echo.phone.ui

object Routes {
    const val ONBOARDING = "onboarding"
    const val HOME = "home"
    const val QUERY = "query"
    const val MINE = "mine"
    const val MEMORY_DETAIL = "memory/{memoryId}"
    const val SPACE_DETAIL = "space/{spaceId}"
    const val PERSONS = "persons"
    const val SPACES = "spaces"
    const val QUALITY_TIME = "quality_time"
    const val DEVICE = "device"
    const val STORAGE = "storage"
    const val HELP = "help"
    const val FAVORITES = "favorites"

    fun memoryDetail(id: String) = "memory/$id"
    fun spaceDetail(id: String) = "space/$id"
}
