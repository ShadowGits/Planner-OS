package dev.planneros.android

import org.junit.Assert.*
import org.junit.Test

class ApiResponsePolicyTest {
    @Test fun refusedSuccessfulHttpResponseTriggersRollback() {
        assertEquals("Star limit reached", ApiResponsePolicy.failure(200,false,"Star limit reached"))
    }
    @Test fun absentErrorMessageStillRefusesSave() {
        assertNotNull(ApiResponsePolicy.failure(200,false,null))
    }
    @Test fun authenticationErrorsNeverDisplayRawProviderResponse() {
        assertEquals("Access key was rejected. Update Settings.", ApiResponsePolicy.failure(401,false,"private provider text"))
    }
    @Test fun redirectedRequestsAreNotAcceptedAsSaved() {
        assertNotNull(ApiResponsePolicy.failure(302,null,null))
    }
    @Test fun explicitSuccessPasses() { assertNull(ApiResponsePolicy.failure(200,true,"Saved")) }
    @Test fun missingSuccessEnvelopeDoesNotConfirmAMutation() { assertNotNull(ApiResponsePolicy.failure(200,null,null)) }
}
