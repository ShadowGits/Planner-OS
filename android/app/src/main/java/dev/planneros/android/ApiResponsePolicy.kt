package dev.planneros.android

class PlannerHttpException(val statusCode: Int, message: String): java.io.IOException(message)

object ApiResponsePolicy {
    fun failure(status: Int, success: Boolean?, message: String?): String? = when {
        status == 401 -> "Access key was rejected. Update Settings."
        status !in 200..299 -> message?.takeIf { it.isNotBlank() } ?: "Server returned $status. Changes were not saved."
        success == false -> message?.takeIf { it.isNotBlank() } ?: "Changes were refused by the planner."
        success == null -> "Server returned an invalid planner response. Changes were not confirmed."
        else -> null
    }
}
