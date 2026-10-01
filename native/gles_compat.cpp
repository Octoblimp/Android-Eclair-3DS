/* Static-EGL compatibility entry points for Eclair's libagl.
 * The normal GLES_CM shared wrapper supplies these symbols; Android3DS links
 * the software driver directly into one static app_process instead. */
#include <string.h>
#include <GLES/gl.h>
#include <GLES/glext.h>

extern "C" {
void glColorPointerBounds(GLint s, GLenum t, GLsizei st, const GLvoid *p, GLsizei)
{ glColorPointer(s, t, st, p); }
void glNormalPointerBounds(GLenum t, GLsizei st, const GLvoid *p, GLsizei)
{ glNormalPointer(t, st, p); }
void glTexCoordPointerBounds(GLint s, GLenum t, GLsizei st, const GLvoid *p, GLsizei)
{ glTexCoordPointer(s, t, st, p); }
void glVertexPointerBounds(GLint s, GLenum t, GLsizei st, const GLvoid *p, GLsizei)
{ glVertexPointer(s, t, st, p); }

void glTexParameterxv(GLenum t, GLenum p, const GLfixed *v)
{ if (v) glTexParameterx(t, p, v[0]); }
void glTexParameterfv(GLenum t, GLenum p, const GLfloat *v)
{ if (v) glTexParameterf(t, p, v[0]); }
void glTexEnviv(GLenum t, GLenum p, const GLint *v)
{ if (v) glTexEnvx(t, p, v[0]); }
void glTexEnvi(GLenum t, GLenum p, GLint v) { glTexEnvx(t, p, v); }

void glPointParameterxv(GLenum, const GLfixed *) {}
void glPointParameterx(GLenum, GLfixed) {}
void glPointParameterfv(GLenum, const GLfloat *) {}
void glPointParameterf(GLenum, GLfloat) {}
void glPointSizePointerOES(GLenum, GLsizei, const GLvoid *) {}
GLboolean glIsTexture(GLuint) { return GL_FALSE; }
GLboolean glIsEnabled(GLenum) { return GL_FALSE; }
GLboolean glIsBuffer(GLuint) { return GL_FALSE; }

void glGetTexParameterxv(GLenum, GLenum, GLfixed *v) { if (v) *v = 0; }
void glGetTexParameteriv(GLenum, GLenum, GLint *v) { if (v) *v = 0; }
void glGetTexParameterfv(GLenum, GLenum, GLfloat *v) { if (v) *v = 0; }
void glGetTexEnvxv(GLenum, GLenum, GLfixed *v) { if (v) *v = 0; }
void glGetTexEnviv(GLenum, GLenum, GLint *v) { if (v) *v = 0; }
void glGetTexEnvfv(GLenum, GLenum, GLfloat *v) { if (v) *v = 0; }
void glGetMaterialxv(GLenum, GLenum, GLfixed *v) { if (v) memset(v, 0, 4*sizeof(*v)); }
void glGetMaterialfv(GLenum, GLenum, GLfloat *v) { if (v) memset(v, 0, 4*sizeof(*v)); }
void glGetLightxv(GLenum, GLenum, GLfixed *v) { if (v) memset(v, 0, 4*sizeof(*v)); }
void glGetLightfv(GLenum, GLenum, GLfloat *v) { if (v) memset(v, 0, 4*sizeof(*v)); }
void glGetFloatv(GLenum, GLfloat *v) { if (v) *v = 0; }
void glGetFixedv(GLenum, GLfixed *v) { if (v) *v = 0; }
void glGetClipPlanex(GLenum, GLfixed *v) { if (v) memset(v, 0, 4*sizeof(*v)); }
void glGetClipPlanef(GLenum, GLfloat *v) { if (v) memset(v, 0, 4*sizeof(*v)); }
void glGetBooleanv(GLenum, GLboolean *v) { if (v) *v = GL_FALSE; }
void glColor4ub(GLubyte r, GLubyte g, GLubyte b, GLubyte a)
{ glColor4f(r / 255.0f, g / 255.0f, b / 255.0f, a / 255.0f); }
}
