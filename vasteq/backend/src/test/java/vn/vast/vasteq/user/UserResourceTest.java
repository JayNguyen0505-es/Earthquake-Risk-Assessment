package vn.vast.vasteq.user;

import io.quarkus.test.junit.QuarkusTest;
import io.quarkus.narayana.jta.QuarkusTransaction;
import io.smallrye.jwt.build.Jwt;
import jakarta.inject.Inject;
import org.junit.jupiter.api.*;
import java.util.Map;
import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.*;

@QuarkusTest
class UserResourceTest {
    static final String ROOT="/api/v1/user";
    static final String PASSWORD="correct-password-123";
    @Inject UserRepository repository;
    @Inject PasswordHasher passwords;

    @BeforeEach void clean(){QuarkusTransaction.requiringNew().run(()->repository.deleteAll());}
    long register(String email){Number id=given().contentType("application/json").body(Map.of("email",email,"password",PASSWORD,"displayName","Test User"))
        .post(ROOT+"/register").then().statusCode(201).extract().path("id");return id.longValue();}
    String login(String email){return given().contentType("application/json").body(Map.of("email",email,"password",PASSWORD))
        .post(ROOT+"/login").then().statusCode(200).header("Cache-Control","no-store").body("tokenType",is("Bearer")).extract().path("accessToken");}
    String admin(){
        QuarkusTransaction.requiringNew().run(()->{
            User user=new User();user.email="admin@example.com";user.displayName="Admin";user.passwordHash=passwords.hash(PASSWORD);user.role=User.Role.admin;repository.persist(user);
        });
        return login("admin@example.com");
    }
    @Test void registrationNormalizesAndRejectsDuplicates(){
        register("  PERSON@Example.com  ");
        given().contentType("application/json").body(Map.of("email","person@example.com","password",PASSWORD,"displayName","Another"))
            .post(ROOT+"/register").then().statusCode(409).body("code",is("email_exists"));
        given().auth().oauth2(login("person@example.com")).get(ROOT+"/me").then().statusCode(200)
            .body("email",is("person@example.com")).body("role",is("user")).body(not(containsString("password")));
    }
    @Test void registrationCannotAssignRolesAndValidatesInput(){
        given().contentType("application/json").body(Map.of("email","person@example.com","password",PASSWORD,"displayName","Test","role","admin"))
            .post(ROOT+"/register").then().statusCode(400);
        given().contentType("application/json").body(Map.of("email","invalid","password","short","displayName"," "))
            .post(ROOT+"/register").then().statusCode(400);
        given().contentType("application/json").body("null").post(ROOT+"/register").then().statusCode(400);
    }
    @Test void loginRejectsInvalidCredentialsAndMissingBearer(){
        register("person@example.com");
        for(String email:new String[]{"person@example.com","missing@example.com"})
            given().contentType("application/json").body(Map.of("email",email,"password","incorrect"))
                .post(ROOT+"/login").then().statusCode(401);
        given().get(ROOT+"/me").then().statusCode(401);
        given().auth().oauth2("invalid-token").get(ROOT+"/me").then().statusCode(401);
    }
    @Test void usersCanEditTheirProfileButCannotManageOtherAccounts(){
        long id=register("person@example.com");String token=login("person@example.com");
        given().auth().oauth2(token).contentType("application/json").body(Map.of("displayName","Updated","email","new@example.com"))
            .patch(ROOT+"/me").then().statusCode(200).body("displayName",is("Updated"));
        given().auth().oauth2(token).get(ROOT).then().statusCode(403);
        given().auth().oauth2(token).get(ROOT+"/"+id).then().statusCode(403);
        given().auth().oauth2(token).contentType("application/json").body(Map.of("role","admin"))
            .patch(ROOT+"/me").then().statusCode(400);
        given().auth().oauth2(token).contentType("application/json").body(Map.of()).patch(ROOT+"/me").then().statusCode(400);
    }
    @Test void passwordChangeRequiresCurrentPasswordAndDoesNotRevokeJwt(){
        register("person@example.com");String token=login("person@example.com");
        given().auth().oauth2(token).contentType("application/json").body(Map.of("currentPassword","wrong","newPassword","new-password-123"))
            .put(ROOT+"/me/password").then().statusCode(401);
        given().auth().oauth2(token).contentType("application/json").body(Map.of("currentPassword",PASSWORD,"newPassword","new-password-123"))
            .put(ROOT+"/me/password").then().statusCode(204);
        given().auth().oauth2(token).get(ROOT+"/me").then().statusCode(200);
        given().contentType("application/json").body(Map.of("email","person@example.com","password",PASSWORD)).post(ROOT+"/login").then().statusCode(401);
        given().contentType("application/json").body(Map.of("email","person@example.com","password","new-password-123")).post(ROOT+"/login").then().statusCode(200);
    }
    @Test void adminCanCreateListReadUpdateAndDisable(){
        String token=admin();
        Number id=given().auth().oauth2(token).contentType("application/json")
            .body(Map.of("email","guest@example.com","password",PASSWORD,"displayName","Guest","role","guest"))
            .post(ROOT).then().statusCode(201).body("role",is("guest")).extract().path("id");
        String guestToken=login("guest@example.com");
        given().auth().oauth2(token).get(ROOT+"?limit=1&offset=0").then().statusCode(200).body("items.size()",is(1)).body("total",is(2));
        given().auth().oauth2(token).get(ROOT+"/"+id).then().statusCode(200).body("email",is("guest@example.com"));
        given().auth().oauth2(token).contentType("application/json").body(Map.of("role","user","displayName","Changed"))
            .patch(ROOT+"/"+id).then().statusCode(200).body("role",is("user"));
        given().auth().oauth2(token).delete(ROOT+"/"+id).then().statusCode(204);
        given().auth().oauth2(token).get(ROOT+"/"+id).then().statusCode(200).body("enabled",is(false));
        given().auth().oauth2(guestToken).get(ROOT+"/me").then().statusCode(401);
        given().contentType("application/json").body(Map.of("email","guest@example.com","password",PASSWORD)).post(ROOT+"/login").then().statusCode(401);
    }
    @Test void adminValidationAndLastAdminProtection(){
        String token=admin();Number id=given().auth().oauth2(token).get(ROOT+"/me").path("id");
        given().auth().oauth2(token).delete(ROOT+"/"+id).then().statusCode(409).body("code",is("last_admin"));
        given().auth().oauth2(token).contentType("application/json").body(Map.of("role","user")).patch(ROOT+"/"+id).then().statusCode(409);
        given().auth().oauth2(token).get(ROOT+"/999999").then().statusCode(404);
        given().auth().oauth2(token).get(ROOT+"?limit=101").then().statusCode(400);
        given().auth().oauth2(token).get(ROOT+"?offset=-1").then().statusCode(400);
    }
    @Test void expiredAndWrongIssuerTokensAreRejected(){
        long id=register("person@example.com");
        String expired=Jwt.issuer("https://vasteq.local").subject(""+id).audience("vasteq-api").groups("user").issuedAt(1).expiresAt(2).sign();
        String wrong=Jwt.issuer("https://other.example").subject(""+id).audience("vasteq-api").groups("user").sign();
        given().auth().oauth2(expired).get(ROOT+"/me").then().statusCode(401);
        given().auth().oauth2(wrong).get(ROOT+"/me").then().statusCode(401);
    }
}
