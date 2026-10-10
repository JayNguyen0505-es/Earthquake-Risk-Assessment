package vn.vast.vasteq.user;

import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.ExceptionMapper;
import jakarta.ws.rs.ext.Provider;

@Provider
public class ApiExceptionMapper implements ExceptionMapper<ApiException> {
    public record Error(String code, String message) {}
    public Response toResponse(ApiException exception) {
        return Response.status(exception.status).entity(new Error(exception.code, exception.getMessage())).build();
    }
}
